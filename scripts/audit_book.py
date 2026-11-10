"""Audit one finished literary translation before auto-approving it.

The queue runner already validates the EPUB pair and runs EPUBCheck. This
script adds the editorial gates that a human would otherwise check:

- glossary target coverage and forbidden renderings;
- pt-PT markers, English leakage, repetition and length ratio;
- five source/target samples reviewed by a cheap cloud model (Haiku).

It is deliberately conservative: a missing API key, an API error or a budget
cap breach fails the audit and leaves the book in ``needs_review``.

Usage:
    python scripts/audit_book.py --book-id 10 --job-id 19 \
      --report data/queue-runs/howling-dark.report.json --max-cloud-usd 0.05
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.literary.metrics import english_leakage, length_ratio, repetition_ratio  # noqa: E402
from src.literary.queue import QueueStore  # noqa: E402
from src.literary.resources import compile_for_book, load_tree  # noqa: E402
from src.literary.run_plan import build_run_plan  # noqa: E402
from src.literary.validation import target_present  # noqa: E402

LEDGER = ROOT / "data" / "cost_ledger.jsonl"
AUDIT_ROOT = ROOT / "data" / "audits"

PT_PT_PATTERNS = [
    r"\btu\b",
    r"\bdespertaste\b",
    r"\bquil[oó]metros?\b",
    r"\bcontacto\b",
    r"\bde facto\b",
    r"\bdem[oó]nio\b",
    r"\ba dan[cç]ar\b",
    r"\bestamos a\b",
    r"\bconvosco\b",
    r"\bcompreendes\b",
    r"\bencontr[aá]mos\b",
    r"\btrav[aá]mos\b",
    r"\bouvistes\b",
    r"\bpr[eé]mios?\b",
    r"\bF[eé]nix\b",
    r"\bse tinha deslocado\b",
    r"\bfazer-vos\b",
    r"\bv[oó]s\b",
]

TRANSLATED_CATEGORIES = {
    "character",
    "title",
    "location",
    "organization",
    "concept",
    "other",
    "item",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "book"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _epub_text(path: Path) -> Tuple[str, List[Tuple[str, List[str]]]]:
    """Return full text and (xhtml name, paragraphs) pairs."""
    files: List[Tuple[str, List[str]]] = []
    full: List[str] = []
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm"))
            and not name.startswith("META-INF/")
        ]
        for name in sorted(names):
            raw = archive.read(name).decode("utf-8", errors="replace")
            raw = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.S | re.I)
            raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
            raw = re.sub(r"</(p|div|h[1-6]|li|blockquote|section)>", "\n", raw, flags=re.I)
            raw = re.sub(r"<[^>]+>", " ", raw)
            text = html.unescape(raw)
            paragraphs = []
            for part in text.split("\n"):
                part = re.sub(r"\s+", " ", part).strip()
                if len(part.split()) >= 5:
                    paragraphs.append(part)
            if paragraphs:
                files.append((name, paragraphs))
                full.extend(paragraphs)
    return "\n\n".join(full), files


def _sample_pairs(
    source_files: List[Tuple[str, List[str]]],
    target_files: List[Tuple[str, List[str]]],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    target_by_name = {name: paragraphs for name, paragraphs in target_files}
    candidates = [
        (name, paragraphs)
        for name, paragraphs in source_files
        if name in target_by_name and len(paragraphs) >= 4
    ]
    if not candidates:
        return []
    if len(candidates) > limit:
        step = max(1, len(candidates) // limit)
        candidates = candidates[::step][:limit]
    samples = []
    for name, source_paragraphs in candidates:
        target_paragraphs = target_by_name[name]
        best: Optional[Tuple[int, str, str]] = None
        for index, source in enumerate(source_paragraphs):
            words = len(source.split())
            if not 40 <= words <= 220:
                continue
            if index >= len(target_paragraphs):
                continue
            target = target_paragraphs[index]
            target_words = len(target.split())
            if not target_words:
                continue
            ratio = target_words / words
            if 0.55 <= ratio <= 1.8:
                best = (index, source, target)
                break
        if best:
            index, source, target = best
            samples.append(
                {
                    "id": f"{name}:{index}",
                    "file": name,
                    "paragraph": index,
                    "source": source,
                    "target": target,
                }
            )
    return samples


def _load_glossary_snapshot(path: Path) -> List[Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    terms = []
    for row in data.get("terms") or []:
        if not isinstance(row, dict) or not row.get("source"):
            continue
        forms = [
            part.strip()
            for part in str(row.get("source") or "").split("|")
            if part.strip()
        ]
        if not forms:
            continue
        target = str(row.get("target") or "")
        aliases = forms[1:]
        terms.append(
            SimpleNamespace(
                source=forms[0],
                target=target,
                category=str(row.get("category") or "other"),
                aliases=aliases,
                alias_targets={alias: target for alias in aliases},
                forbidden=list(row.get("forbidden") or []),
                policy=str(row.get("policy") or ""),
                confidence=str(row.get("confidence") or ""),
                source_reference=str(row.get("source_reference") or ""),
            )
        )
    return terms


def _term_form_map(terms: List[Any]) -> Dict[str, Tuple[str, Tuple[str, ...]]]:
    mapping: Dict[str, Tuple[str, Tuple[str, ...]]] = {}
    for term in terms:
        forbidden = tuple(
            sorted(str(item) for item in (getattr(term, "forbidden", []) or []))
        )
        mapping[term.source] = (term.target, forbidden)
        alias_targets = getattr(term, "alias_targets", {}) or {}
        for alias in getattr(term, "aliases", []) or []:
            mapping[alias] = (alias_targets.get(alias, term.target), forbidden)
    return mapping


def _term_audit(
    book: Any,
    source_text: str,
    target_text: str,
    *,
    glossary_path: Optional[Path] = None,
) -> Dict[str, Any]:
    snapshot_terms: List[Any] = []
    current_terms: List[Any] = []
    current_map: Dict[str, Tuple[str, Tuple[str, ...]]] = {}
    snapshot = ""
    try:
        plan = build_run_plan(book)
        scopes = plan.get("scopes") or {}
        tree = load_tree(str(ROOT / "literary-resources"))
        compiled = compile_for_book(
            tree,
            scopes.get("author", ""),
            scopes.get("universe", ""),
            scopes.get("subseries", ""),
            scopes.get("book", ""),
            book_order=book.series_index,
        )
        current_terms = compiled.glossary.terms
        current_map = _term_form_map(current_terms)
    except Exception as exc:
        if not (glossary_path and glossary_path.exists()):
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "coverage": None,
                "forbidden_hits": [],
                "missing": [],
            }

    if glossary_path and glossary_path.exists():
        snapshot_terms = _load_glossary_snapshot(glossary_path)
        snapshot = str(glossary_path)
        terms = snapshot_terms
    else:
        terms = current_terms

    source_cf = source_text.casefold()
    eligible = 0
    hits = 0
    missing: List[Dict[str, str]] = []
    forbidden_hits: List[Dict[str, Any]] = []
    drift: List[Dict[str, Any]] = []
    for term in terms:
        if snapshot_terms and current_map:
            current = current_map.get(term.source)
            if current is None:
                drift.append(
                    {
                        "source": term.source,
                        "snapshot_target": term.target,
                        "current_target": "",
                        "reason": "removed from the current glossary",
                    }
                )
                continue
            current_target, current_forbidden = current
            if current_target != term.target or set(current_forbidden) != set(term.forbidden):
                drift.append(
                    {
                        "source": term.source,
                        "snapshot_target": term.target,
                        "current_target": current_target,
                        "reason": "glossary changed after the run",
                    }
                )
                continue
        forms = [term.source] + list(getattr(term, "aliases", []) or [])
        if not any(form.casefold() in source_cf for form in forms if form):
            continue
        targets = [term.target]
        alias_targets = getattr(term, "alias_targets", {}) or {}
        targets.extend(alias_targets.values())
        targets = [target for target in targets if target]
        if targets:
            eligible += 1
            if any(target_present(target, target_text) for target in targets):
                hits += 1
            else:
                missing.append(
                    {
                        "source": term.source,
                        "target": term.target,
                        "category": getattr(term, "category", ""),
                    }
                )
        for forbidden in getattr(term, "forbidden", []) or []:
            count = len(
                re.findall(
                    rf"\b{re.escape(str(forbidden))}\b",
                    target_text,
                    flags=re.I,
                )
            )
            if count:
                forbidden_hits.append({"source": term.source, "forbidden": forbidden, "count": count})
    coverage = (hits / eligible) if eligible else 1.0
    return {
        "ok": True,
        "terms": len(terms),
        "snapshot": snapshot,
        "snapshot_terms": len(snapshot_terms) if snapshot_terms else None,
        "current_terms": len(current_terms),
        "drift": drift[:50],
        "eligible": eligible,
        "hits": hits,
        "coverage": round(coverage, 4),
        "missing": missing[:25],
        "forbidden_hits": forbidden_hits,
    }


def _text_metrics(source_text: str, target_text: str) -> Dict[str, Any]:
    target_words = max(1, len(re.findall(r"\b\w+\b", target_text)))
    pt_hits = []
    for pattern in PT_PT_PATTERNS:
        matches = re.findall(pattern, target_text, flags=re.I)
        if matches:
            pt_hits.append({"pattern": pattern, "count": len(matches)})
    pt_total = sum(item["count"] for item in pt_hits)
    try:
        leakage = english_leakage(target_text)
    except Exception:
        leakage = None
    try:
        repetition = repetition_ratio(target_text)
    except Exception:
        repetition = None
    try:
        ratio = length_ratio(source_text, target_text)
    except Exception:
        ratio = None
    return {
        "words": target_words,
        "pt_pt_hits": pt_hits,
        "pt_pt_total": pt_total,
        "pt_pt_per_100k": round(pt_total / target_words * 100_000, 2),
        "english_leakage": leakage,
        "repetition_ratio": repetition,
        "length_ratio": ratio,
    }


def _cloud_prompt(samples: List[Dict[str, Any]]) -> str:
    lines = [
        "You are auditing a literary translation from English into Brazilian Portuguese.",
        "For each pair, judge fidelity, naturalness, terminology and register on a 1-5 scale.",
        "If the target does not correspond to the source paragraph, set alignment_suspect to true and do not score it.",
        "Count meaning errors, omissions and additions. Flag pt-PT forms (tu, contacto, de facto, demónio, a dançar) and English leakage.",
        "Return ONLY a JSON object with this shape:",
        '{"items":[{"id":"...","alignment_suspect":false,"fidelity":1,"naturalness":1,"terminology":1,"register":1,"meaning_errors":0,"notes":"short Portuguese note"}],"summary":"short Portuguese summary"}',
        "Do not use markdown fences. Do not add commentary outside the JSON.",
        "",
    ]
    for sample in samples:
        lines.extend(
            [
                f"ID: {sample['id']}",
                "SOURCE:",
                sample["source"],
                "",
                "TARGET:",
                sample["target"],
                "",
            ]
        )
    return "\n".join(lines)


def _cloud_audit(
    samples: List[Dict[str, Any]],
    *,
    max_cloud_usd: float,
    book_title: str,
) -> Dict[str, Any]:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5").strip()
    if not key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY missing", "passed": False}
    if not samples:
        return {"ok": False, "error": "no aligned samples", "passed": False}

    payload = {
        "model": model,
        "max_tokens": 1600,
        "thinking": {"type": "disabled"},
        "system": "You are a meticulous bilingual literary editor. Judge only the supplied source and target.",
        "messages": [{"role": "user", "content": _cloud_prompt(samples)}],
    }
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        if not response.ok:
            return {
                "ok": False,
                "error": f"HTTP {response.status_code}: {response.text[:800]}",
                "passed": False,
            }
        data = response.json()
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "passed": False}

    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cost = input_tokens * 0.10 / 1_000_000 + output_tokens * 0.50 / 1_000_000
    if cost > max_cloud_usd:
        return {
            "ok": False,
            "error": f"cloud audit cost ${cost:.4f} exceeds cap ${max_cloud_usd:.4f}",
            "passed": False,
            "cost_usd": round(cost, 6),
        }

    content = ""
    for block in data.get("content") or []:
        if block.get("type") == "text":
            content += block.get("text", "")
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return {"ok": False, "error": "cloud audit returned no JSON", "passed": False}
    try:
        parsed = json.loads(content[start : end + 1])
    except ValueError as exc:
        return {"ok": False, "error": f"invalid cloud JSON: {exc}", "passed": False}

    items = parsed.get("items") or []
    scored = [
        item
        for item in items
        if isinstance(item, dict) and not item.get("alignment_suspect")
    ]
    if len(scored) < 3:
        return {
            "ok": False,
            "error": "fewer than three aligned scored samples",
            "passed": False,
            "items": items,
            "cost_usd": round(cost, 6),
        }

    def average(key_name: str) -> float:
        values = [float(item.get(key_name) or 0) for item in scored]
        return round(sum(values) / len(values), 3) if values else 0.0

    meaning_errors = sum(int(item.get("meaning_errors") or 0) for item in scored)
    result = {
        "ok": True,
        "passed": average("fidelity") >= 3.5
        and average("naturalness") >= 3.5
        and meaning_errors <= 1
        and len(scored) >= 3,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
        "averages": {
            "fidelity": average("fidelity"),
            "naturalness": average("naturalness"),
            "terminology": average("terminology"),
            "register": average("register"),
        },
        "meaning_errors": meaning_errors,
        "scored_samples": len(scored),
        "items": items,
        "summary": parsed.get("summary", ""),
    }
    _record_cost(book_title, model, input_tokens, output_tokens, cost)
    return result


def _record_cost(book_title: str, model: str, input_tokens: int, output_tokens: int, cost: float) -> None:
    row = {
        "timestamp": _utc(),
        "provider": "anthropic",
        "model": model,
        "book": book_title,
        "stage": "auto-audit",
        "prompt_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
        "estimated": False,
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _resolve_target(report: Dict[str, Any], book: Any, outputs: Path) -> Path:
    for key in ("refined_output", "fixed_output", "output"):
        value = str(report.get(key) or "").strip()
        if value and Path(value).exists():
            return Path(value)
    name = f"{book.title} (pt-BR).epub"
    return outputs / name


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-id", type=int, required=True)
    parser.add_argument("--job-id", type=int, default=0)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "literary_queue.db")
    parser.add_argument("--outputs", type=Path, default=ROOT / "translated_files")
    parser.add_argument("--max-cloud-usd", type=float, default=0.05)
    parser.add_argument("--no-cloud", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    store = QueueStore(args.db)
    book = store.get_book(args.book_id)
    job = store.get_job(args.job_id) if args.job_id else store.latest_job(args.book_id)
    store.close()
    if not book or not job:
        raise SystemExit("book or job not found")

    report: Dict[str, Any] = {}
    if args.report and args.report.exists():
        report = json.loads(args.report.read_text(encoding="utf-8"))
    target = _resolve_target(report, book, args.outputs)
    source = Path(book.source_path)
    if not source.exists() or not target.exists():
        raise SystemExit(f"source or target missing: source={source} target={target}")

    source_text, source_files = _epub_text(source)
    target_text, target_files = _epub_text(target)
    samples = _sample_pairs(source_files, target_files)
    glossary_path = str((report.get("assets") or {}).get("glossary_host") or "").strip()
    terms = _term_audit(
        book,
        source_text,
        target_text,
        glossary_path=Path(glossary_path) if glossary_path else None,
    )
    metrics = _text_metrics(source_text, target_text)

    validation = report.get("validation") or {}
    epubcheck = report.get("epubcheck") or {}
    gate_ok = bool(report.get("gate_passed"))
    epub_ok = bool(validation.get("passed")) and int(epubcheck.get("errors") or 0) == 0
    if not report:
        gate_ok = False
        epub_ok = False

    cloud: Dict[str, Any] = {"ok": False, "passed": False, "error": "not run"}
    if not args.no_cloud:
        cloud = _cloud_audit(samples, max_cloud_usd=args.max_cloud_usd, book_title=book.title)
    else:
        cloud = {"ok": True, "passed": True, "error": "cloud audit disabled"}

    reasons: List[str] = []
    if not gate_ok or not epub_ok:
        reasons.append("queue gate (validation/EPUBCheck) failed or report missing")
    if not terms.get("ok"):
        reasons.append(f"glossary audit failed: {terms.get('error')}")
    elif float(terms.get("coverage") or 0) < 0.90:
        reasons.append(f"glossary coverage {terms.get('coverage')} < 0.90")
    if terms.get("forbidden_hits"):
        reasons.append(f"{len(terms['forbidden_hits'])} forbidden rendering(s) found")
    if metrics.get("pt_pt_per_100k", 0) > 50:
        reasons.append(f"pt-PT markers {metrics['pt_pt_per_100k']} per 100k > 50")
    if metrics.get("english_leakage") is not None and metrics["english_leakage"] > 0.01:
        reasons.append(f"English leakage {metrics['english_leakage']} > 0.01")
    if metrics.get("repetition_ratio") is not None and metrics["repetition_ratio"] > 0.05:
        reasons.append(f"repetition {metrics['repetition_ratio']} > 0.05")
    if metrics.get("length_ratio") is not None and not 0.80 <= metrics["length_ratio"] <= 1.20:
        reasons.append(f"length ratio {metrics['length_ratio']} outside 0.80-1.20")
    if not cloud.get("passed"):
        reasons.append(f"cloud audit failed: {cloud.get('error', 'unknown')}")

    passed = not reasons
    audit = {
        "created_at": _utc(),
        "book": book.title,
        "book_id": book.id,
        "job_id": job.get("id"),
        "model": book.model,
        "provider": book.provider,
        "source": str(source),
        "target": str(target),
        "report": str(args.report) if args.report else "",
        "passed": passed,
        "reasons": reasons,
        "gate": {
            "queue_gate": gate_ok,
            "epubcheck_errors": int(epubcheck.get("errors") or 0),
            "validation_blocking": validation.get("blocking"),
        },
        "terms": terms,
        "metrics": metrics,
        "samples": samples,
        "cloud": cloud,
    }

    out_dir = args.out or (AUDIT_ROOT / f"{_slug(book.title)}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "samples.jsonl").write_text(
        "\n".join(json.dumps(sample, ensure_ascii=False) for sample in samples) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# Audit: {book.title}",
        "",
        f"- Result: **{'PASS' if passed else 'FAIL'}**",
        f"- Generated: {audit['created_at']}",
        f"- Model: `{book.model}` ({book.provider})",
        f"- Target: `{target}`",
        "",
        "## Gates",
        "",
        f"- Queue validation/EPUBCheck: {gate_ok}/{epub_ok} (errors {audit['gate']['epubcheck_errors']}, blocking {audit['gate']['validation_blocking']})",
        f"- Glossary coverage: {terms.get('coverage')} ({terms.get('hits')}/{terms.get('eligible')}); forbidden hits: {len(terms.get('forbidden_hits') or [])}",
        f"- pt-PT markers: {metrics.get('pt_pt_per_100k')} per 100k",
        f"- English leakage: {metrics.get('english_leakage')}",
        f"- Repetition: {metrics.get('repetition_ratio')}",
        f"- Length ratio: {metrics.get('length_ratio')}",
        f"- Cloud samples: {cloud.get('scored_samples')} scored; averages {cloud.get('averages')}; meaning errors {cloud.get('meaning_errors')}",
        "",
        "## Reasons",
        "",
    ]
    if reasons:
        lines.extend(f"- {reason}" for reason in reasons)
    else:
        lines.append("- All gates passed.")
    lines.extend(["", "## Missing glossary targets", ""])
    for item in (terms.get("missing") or [])[:15]:
        lines.append(f"- {item['source']} -> {item['target']} ({item['category']})")
    lines.extend(["", "## Cloud notes", ""])
    for item in cloud.get("items") or []:
        lines.append(f"- {item.get('id')}: {item.get('notes', '')}")
    (out_dir / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"passed": passed, "audit": str(out_dir / "audit.json"), "reasons": reasons}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
