"""Fase D: aligned corpus, repeated runs, VRAM sampling and a blind report.

Runs the installed Ollama models on the aligned Farseer corpus with the
production Farseer resources. Each excerpt is translated ``--repeats`` times;
the script samples GPU memory/utilization while the runner is active and
aggregates quality/speed. The blind review sheet hides model identities.

Usage:
    python scripts/benchmark_fase_d.py --repeats 3
    python scripts/benchmark_fase_d.py --repeats 1 --limit 5 --out-root data/benchmark/fase-d-pilot
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.literary import runner  # noqa: E402
from src.literary.resources import assemble_style, compile_for_book, load_tree  # noqa: E402

DEFAULT_MODELS = ["hy-mt2-7b", "hy-mt2-7b-q6", "index-translate-9b", "qwen3-8b"]


def _resources() -> tuple[Dict[str, str], str]:
    tree = load_tree(str(ROOT / "literary-resources"))
    compiled = compile_for_book(
        tree,
        "robin-hobb",
        "realm-of-the-elderlings",
        "farseer",
        "assassins-apprentice",
        book_order=3,
    )
    glossary: Dict[str, str] = {}
    for term in compiled.glossary.terms:
        target = term.effective_target()
        for form in term.source_forms():
            glossary[form] = target
    style = assemble_style(compiled.style).get("translation", "") if compiled.style else ""
    return glossary, style


class VramSampler:
    def __init__(self) -> None:
        self.samples: List[Dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.baseline_mib: Optional[int] = None

    def _read(self) -> Optional[tuple[int, int]]:
        try:
            output = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            return None
        line = (output or "").strip().splitlines()[0] if output.strip() else ""
        try:
            memory, utilization = [int(part.strip()) for part in line.split(",")[:2]]
        except (ValueError, IndexError):
            return None
        return memory, utilization

    def start(self) -> None:
        first = self._read()
        if first:
            self.baseline_mib = first[0]
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            sample = self._read()
            if sample:
                self.samples.append({
                    "at": round(time.time(), 3),
                    "memory_mib": sample[0],
                    "utilization_pct": sample[1],
                })
            self._stop.wait(1.0)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def summary(self) -> Dict[str, Any]:
        if not self.samples:
            return {"samples": 0, "baseline_mib": self.baseline_mib}
        memories = [item["memory_mib"] for item in self.samples]
        utilizations = [item["utilization_pct"] for item in self.samples]
        return {
            "samples": len(self.samples),
            "baseline_mib": self.baseline_mib,
            "peak_mib": max(memories),
            "mean_mib": round(statistics.mean(memories), 1),
            "max_utilization_pct": max(utilizations),
            "mean_utilization_pct": round(statistics.mean(utilizations), 1),
            "delta_peak_mib": (max(memories) - self.baseline_mib) if self.baseline_mib else None,
        }


def _percentile(values: List[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return float(ordered[index])


def _mean(values: List[float]) -> float:
    return round(statistics.mean(values), 4) if values else 0.0


def _std(values: List[float]) -> float:
    return round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0


def _aggregate(rows: List[Dict[str, Any]], models: List[str], vram: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"models": {}, "vram": vram, "rows": len(rows)}
    for model in models:
        selected = [row for row in rows if row.get("model") == model and not (row.get("generation") or {}).get("error")]
        chrf = [float(row["metrics"]["chrf"]) for row in selected if row.get("metrics", {}).get("chrf") is not None]
        lengths = [float(row["metrics"]["length_ratio"]) for row in selected if row.get("metrics", {}).get("length_ratio") is not None]
        names = [float(row["metrics"]["name_recall"]) for row in selected if row.get("metrics", {}).get("name_recall") is not None]
        numbers = [float(row["metrics"]["number_recall"]) for row in selected if row.get("metrics", {}).get("number_recall") is not None]
        leaks = [float(row["metrics"]["english_leakage"]) for row in selected if row.get("metrics", {}).get("english_leakage") is not None]
        reps = [float(row["metrics"]["repetition_ratio"]) for row in selected if row.get("metrics", {}).get("repetition_ratio") is not None]
        latencies = [float(row["generation"]["latency_s"]) for row in selected if row.get("generation", {}).get("latency_s")]
        tokens = [int(row["generation"]["output_tokens"]) for row in selected if row.get("generation", {}).get("output_tokens")]
        tok_s = [
            tokens[i] / latencies[i]
            for i in range(min(len(tokens), len(latencies)))
            if latencies[i] > 0
        ]
        result["models"][model] = {
            "n": len(selected),
            "errors": sum(1 for row in rows if row.get("model") == model and (row.get("generation") or {}).get("error")),
            "chrf_mean": _mean(chrf),
            "chrf_std": _std(chrf),
            "length_ratio_mean": _mean(lengths),
            "name_recall_mean": _mean(names),
            "number_recall_mean": _mean(numbers),
            "english_leakage_mean": _mean(leaks),
            "repetition_mean": _mean(reps),
            "latency_mean_s": _mean(latencies),
            "latency_p50_s": round(_percentile(latencies, 0.5), 3),
            "latency_p95_s": round(_percentile(latencies, 0.95), 3),
            "output_tokens_mean": _mean([float(value) for value in tokens]),
            "tokens_per_s_mean": _mean(tok_s),
        }
    return result


def _report(summary: Dict[str, Any], out_path: Path, vram: Dict[str, Any], blind: Dict[str, Any]) -> None:
    lines = [
        "# Fase D — modelo local 8 GB",
        "",
        f"Corpus: `{summary.get('corpus', '')}`",
        f"Repetições: {summary.get('repeats', 0)}",
        f"Excerpts por repetição: {summary.get('excerpts', 0)}",
        "",
        "| Modelo | n | chrF | chrF σ | Length | Name | Number | Leakage | Repetition | p50 s | p95 s | tok/s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, item in summary["models"].items():
        lines.append(
            "| {model} | {n} | {chrf} | {chrf_std} | {length} | {name} | {number} | {leak} | {rep} | {p50} | {p95} | {tps} |".format(
                model=model,
                n=item["n"],
                chrf=item["chrf_mean"],
                chrf_std=item["chrf_std"],
                length=item["length_ratio_mean"],
                name=item["name_recall_mean"],
                number=item["number_recall_mean"],
                leak=item["english_leakage_mean"],
                rep=item["repetition_mean"],
                p50=item["latency_p50_s"],
                p95=item["latency_p95_s"],
                tps=item["tokens_per_s_mean"],
            )
        )
    lines += [
        "",
        "## VRAM",
        "",
        f"- Baseline: {vram.get('baseline_mib')} MiB",
        f"- Pico: {vram.get('peak_mib')} MiB",
        f"- Delta de pico: {vram.get('delta_peak_mib')} MiB",
        f"- Utilização máxima: {vram.get('max_utilization_pct')}%",
        f"- Amostras: {vram.get('samples')}",
        "",
        "## Relatório cego",
        "",
        f"- Revisão: `{blind.get('review_path', '')}`",
        f"- Chave: `{blind.get('key_path', '')}`",
        f"- Entradas: {blind.get('entries', 0)}",
        "",
        "A latência só é comparável com a GPU livre. O relatório cego existe para",
        "revisão humana/LLM; não escolha o vencedor apenas pelo chrF.",
        "",
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="data/benchmark/literary/corpus_aligned_farseer.jsonl")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--out-root", default="data/benchmark/fase-d")
    parser.add_argument("--skip-vram", action="store_true")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"corpus not found: {corpus}", file=sys.stderr)
        return 1
    glossary, style = _resources()
    print(f"resources: {len(glossary)} prompt terms, style {len(style)} chars", flush=True)

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    all_rows: List[Dict[str, Any]] = []
    repeat_vram: List[Dict[str, Any]] = []
    first_run_dir = ""
    summary_template: Dict[str, Any] = {}
    for repeat in range(1, max(1, args.repeats) + 1):
        repeat_root = out_root / f"repeat-{repeat:02d}"
        sampler = None if args.skip_vram else VramSampler()
        if sampler:
            sampler.start()
        print(f"repeat {repeat}: running {args.models}", flush=True)
        try:
            summary = runner.run(
                str(corpus),
                args.models,
                output_root=str(repeat_root),
                endpoint=args.endpoint,
                limit=args.limit,
                glossary=glossary,
                style=style,
            )
        finally:
            if sampler:
                sampler.stop()
        if not first_run_dir:
            first_run_dir = summary.get("run_dir", "")
            summary_template = summary
        for row in summary.get("results", []):
            row["repeat"] = repeat
            all_rows.append(row)
        if sampler:
            repeat_vram.append({"repeat": repeat, "run_dir": summary.get("run_dir"), **sampler.summary()})
        print(f"repeat {repeat}: {len(summary.get('results', []))} rows, dir={summary.get('run_dir')}", flush=True)

    vram = {}
    if repeat_vram:
        peaks = [item["peak_mib"] for item in repeat_vram if item.get("peak_mib")]
        vram = {
            "repeats": repeat_vram,
            "peak_mib": max(peaks) if peaks else None,
            "baseline_mib": repeat_vram[0].get("baseline_mib"),
            "delta_peak_mib": (max(peaks) - repeat_vram[0].get("baseline_mib")) if peaks and repeat_vram[0].get("baseline_mib") else None,
            "max_utilization_pct": max((item.get("max_utilization_pct") or 0) for item in repeat_vram),
            "samples": sum(item.get("samples", 0) for item in repeat_vram),
        }

    aggregate = _aggregate(all_rows, args.models, vram)
    aggregate.update({
        "corpus": str(corpus),
        "repeats": args.repeats,
        "excerpts": summary_template.get("excerpts", 0),
        "run_dir": first_run_dir,
        "rows": len(all_rows),
    })
    (out_root / "fase-d-summary.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    blind = {}
    if first_run_dir:
        blind_dir = out_root / "blind"
        blind_dir.mkdir(parents=True, exist_ok=True)
        review_path = blind_dir / "blind_review.jsonl"
        key_path = blind_dir / "blind_key.json"
        blind = runner.blind_report(first_run_dir, str(review_path), str(key_path))
        blind["review_path"] = str(review_path)
        blind["key_path"] = str(key_path)

    _report(aggregate, out_root / "fase-d-report.md", vram, blind)
    print(json.dumps({"summary": str(out_root / "fase-d-summary.json"), "report": str(out_root / "fase-d-report.md"), "blind": blind}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
