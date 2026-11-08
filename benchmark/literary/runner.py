"""Run the local literary benchmark and write auditable artifacts."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark.literary.adapters import (
    MODELS,
    ModelSpec,
    build_prompt,
    generate_ollama,
    generate_openai_compatible,
)
import yaml

from benchmark.literary.corpus import Excerpt, load_corpus
from benchmark.literary.metrics import score_output


def load_glossary_file(path: str) -> Dict[str, str]:
    """Accept either a flat ``{source: target}`` map or the compiled glossary shape."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("terms"), list):
        glossary: Dict[str, str] = {}
        for term in payload["terms"]:
            if not isinstance(term, dict):
                continue
            target = str(term.get("target") or "").strip()
            if not target:
                continue
            for form in str(term.get("source") or "").split("|"):
                form = form.strip()
                if form:
                    glossary[form] = target
        return glossary
    if not isinstance(payload, dict):
        raise ValueError("glossary must be a JSON object or a compiled glossary with a terms list")
    return {str(source): str(target) for source, target in payload.items()}


def load_style_file(path: str) -> str:
    """Load a style preset YAML (translation block) or plain text."""
    text = Path(path).read_text(encoding="utf-8")
    if path.lower().endswith((".yaml", ".yml")):
        payload = yaml.safe_load(text) or {}
        if isinstance(payload, dict):
            return str(payload.get("translation") or payload.get("refinement") or "")
    return text


def _run_dir(root: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(root) / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def run(
    corpus_path: str,
    model_keys: List[str],
    *,
    output_root: str = "data/benchmark/literary/runs",
    endpoint: str = "http://localhost:11434",
    limit: int = 0,
    glossary: Optional[Dict[str, str]] = None,
    style: str = "",
    dry_run: bool = False,
    allow_cloud: bool = False,
    api_key: str = "",
    openai_endpoint: str = "",
) -> Dict[str, Any]:
    corpus = load_corpus(corpus_path)
    if limit:
        corpus = corpus[:limit]
    out_dir = _run_dir(output_root)
    summary: Dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": os.path.abspath(corpus_path),
        "models": model_keys,
        "excerpts": len(corpus),
        "run_dir": str(out_dir),
        "results": [],
    }
    for key in model_keys:
        if key not in MODELS:
            raise KeyError(f"Unknown model key: {key}")
        spec = MODELS[key]
        rows = []
        for excerpt in corpus:
            messages = build_prompt(spec, excerpt.text, glossary=glossary if spec.supports_glossary else None, style=style if spec.supports_glossary else None)
            if dry_run:
                rows.append({"id": excerpt.id, "book": excerpt.book, "category": excerpt.category, "scenario": spec.key, "dry_run": True, "prompt_messages": messages})
                continue
            if spec.provider == "ollama":
                generation = generate_ollama(spec, messages, endpoint=endpoint)
            elif spec.provider == "openai-compatible":
                if not allow_cloud:
                    generation = type("G", (), {"to_dict": lambda self: {"error": "cloud disabled; pass --allow-cloud"}})()
                elif not api_key or not openai_endpoint:
                    generation = type("G", (), {"to_dict": lambda self: {"error": "missing --api-key or --openai-endpoint"}})()
                else:
                    generation = generate_openai_compatible(spec, messages, endpoint=openai_endpoint, api_key=api_key)
            else:
                raise ValueError(f"Unknown provider: {spec.provider}")
            gen_payload = generation.to_dict() if hasattr(generation, "to_dict") else dict(generation)
            output = gen_payload.get("text", "")
            metrics = score_output(
                excerpt.text,
                output,
                reference=excerpt.reference_pt,
                glossary=glossary if spec.supports_glossary else None,
            )
            row = {
                "id": excerpt.id,
                "book": excerpt.book,
                "author": excerpt.author,
                "chapter_href": excerpt.chapter_href,
                "category": excerpt.category,
                "model": spec.key,
                "model_label": spec.label,
                "native_prompt": spec.native_prompt,
                "glossary_used": bool(glossary) if spec.supports_glossary else False,
                "style_used": bool(style) if spec.supports_glossary else False,
                "generation": gen_payload,
                "metrics": metrics,
                "source_chars": len(excerpt.text),
            }
            rows.append(row)
            summary["results"].append(row)
        with open(out_dir / f"{key}.jsonl", "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def report(run_dir: str, output_path: str = "") -> str:
    rows = []
    for path in sorted(Path(run_dir).glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    lines = [
        "# Literary benchmark run",
        "",
        f"Run directory: `{run_dir}`",
        "",
        "| Book | Category | Model | Latency (s) | Tokens out | chrF | Length ratio | Number recall | Name recall | English leakage | Repetition |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        gen = row.get("generation", {})
        metrics = row.get("metrics", {})
        def fmt(value):
            return "" if value is None else str(value)
        lines.append(
            "| {book} | {category} | {model} | {latency} | {tokens} | {chrf} | {length} | {numbers} | {names} | {leak} | {rep} |".format(
                book=row.get("book", ""),
                category=row.get("category", ""),
                model=row.get("model", ""),
                latency=fmt(gen.get("latency_s")),
                tokens=fmt(gen.get("output_tokens")),
                chrf=fmt(metrics.get("chrf")),
                length=fmt(metrics.get("length_ratio")),
                numbers=fmt(metrics.get("number_recall")),
                names=fmt(metrics.get("name_recall")),
                leak=fmt(metrics.get("english_leakage")),
                rep=fmt(metrics.get("repetition_ratio")),
            )
        )
    text = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(text, encoding="utf-8")
    return text


def blind_report(
    run_dir: str,
    output_path: str = "",
    key_path: str = "",
) -> Dict[str, object]:
    """Write an anonymized review sheet plus a separate label key.

    The review sheet contains only excerpt text and model outputs; the mapping
    from A/B/C to model names lives in ``key_path`` so a human reviewer can be
    blind to the model identity.
    """
    run_path = Path(run_dir)
    summary_path = run_path / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    rows = list(summary.get("results") or [])
    if not rows:
        for path in sorted(run_path.glob("*.jsonl")):
            if path.name == "blind_review.jsonl":
                continue
            with path.open("r", encoding="utf-8") as handle:
                rows.extend(json.loads(line) for line in handle if line.strip())

    model_keys = list(summary.get("models") or [])
    for row in rows:
        key = str(row.get("model") or "")
        if key and key not in model_keys:
            model_keys.append(key)
    if not model_keys:
        raise ValueError("no model results found in the run directory")

    labels = {model: chr(ord("A") + index) for index, model in enumerate(model_keys)}
    corpus_path = str(summary.get("corpus") or "")
    corpus = load_corpus(corpus_path) if corpus_path and Path(corpus_path).exists() else []
    source_by_id = {excerpt.id: excerpt for excerpt in corpus}
    outputs: Dict[tuple, Dict[str, str]] = {}
    for row in rows:
        outputs[(str(row.get("id")), str(row.get("model")))] = row

    review_path = Path(output_path) if output_path else run_path / "blind_review.jsonl"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    entries: List[Dict[str, object]] = []
    for excerpt in corpus:
        for model in model_keys:
            row = outputs.get((excerpt.id, model))
            if row is None:
                continue
            entries.append(
                {
                    "id": excerpt.id,
                    "book": excerpt.book,
                    "category": excerpt.category,
                    "label": labels[model],
                    "source": excerpt.text,
                    "output": (row.get("generation") or {}).get("text", ""),
                }
            )
    with review_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    key_file = Path(key_path) if key_path else run_path / "blind_key.json"
    key_file.write_text(
        json.dumps({"labels": labels, "models": model_keys}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "run_dir": str(run_path),
        "review": str(review_path),
        "key": str(key_file),
        "models": len(model_keys),
        "entries": len(entries),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Literary benchmark runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--corpus", default="data/benchmark/literary/corpus.jsonl")
    run_parser.add_argument("--models", nargs="+", required=True)
    run_parser.add_argument("--endpoint", default="http://localhost:11434")
    run_parser.add_argument("--output-root", default="data/benchmark/literary/runs")
    run_parser.add_argument("--limit", type=int, default=0)
    run_parser.add_argument("--style", default="")
    run_parser.add_argument("--style-file", default="", help="YAML style preset or plain-text style block")
    run_parser.add_argument("--glossary", default="", help="Compiled glossary JSON or a {source: target} map")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--allow-cloud", action="store_true")
    run_parser.add_argument("--api-key", default="")
    run_parser.add_argument("--openai-endpoint", default="")
    report_parser = sub.add_parser("report")
    report_parser.add_argument("--run-dir", required=True)
    report_parser.add_argument("--out", default="")
    blind_parser = sub.add_parser("report-blind", help="Write an anonymized review sheet and a separate key")
    blind_parser.add_argument("--run-dir", required=True)
    blind_parser.add_argument("--out", default="")
    blind_parser.add_argument("--key", default="")
    args = parser.parse_args(argv)
    if args.command == "run":
        glossary = load_glossary_file(args.glossary) if args.glossary else None
        style = load_style_file(args.style_file) if args.style_file else args.style
        summary = run(
            args.corpus,
            args.models,
            output_root=args.output_root,
            endpoint=args.endpoint,
            limit=args.limit,
            glossary=glossary,
            style=style,
            dry_run=args.dry_run,
            allow_cloud=args.allow_cloud,
            api_key=args.api_key,
            openai_endpoint=args.openai_endpoint,
        )
        print(json.dumps({"run_dir": summary["run_dir"], "results": len(summary["results"])}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "report-blind":
        print(json.dumps(blind_report(args.run_dir, args.out, args.key), ensure_ascii=False, indent=2))
        return 0
    print(report(args.run_dir, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
