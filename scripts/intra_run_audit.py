"""Deterministic quality audit while a book is still being translated.

It samples the XHTML files already written to ``data/uploads/<id>/translated_files``
and compares them with the matching source files from the run's EPUB. No cloud
call: glossary coverage, forbidden renderings, pt-PT markers, English leakage,
repetition and length ratio. The report is written under
``data/audits/intra-run`` and the watchdog runs it every 100 chunks.

Usage:
    python scripts/intra_run_audit.py --book-id 10 --translation-id cli_c00e8ea2
    python scripts/intra_run_audit.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import audit_book  # noqa: E402
from src.literary.queue import QueueStore  # noqa: E402

QUEUE_DB = ROOT / "data" / "literary_queue.db"
HEALTH = ROOT / "data" / "literary_queue.health.json"
UPLOADS = ROOT / "data" / "uploads"
COMPILED = ROOT / "data" / "compiled"
REPORTS = ROOT / "data" / "audits" / "intra-run"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_health() -> Dict[str, Any]:
    try:
        data = json.loads(HEALTH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _active_book() -> Optional[Dict[str, Any]]:
    try:
        conn = __import__("sqlite3").connect(
            f"file:{QUEUE_DB.as_posix()}?mode=ro", uri=True, timeout=10
        )
        conn.row_factory = __import__("sqlite3").Row
        try:
            row = conn.execute(
                "SELECT id, title FROM books WHERE status IN "
                "('preparing','translating','reviewing','validating') "
                "ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    except Exception:
        return None


def _source_epub(upload_dir: Path) -> Optional[Path]:
    candidates = [
        path for path in upload_dir.glob("*.epub")
        if path.is_file() and "translated" not in path.name.lower()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_size)


def _target_files(upload_dir: Path) -> List[Path]:
    base = upload_dir / "translated_files"
    if not base.exists():
        return []
    return sorted(base.rglob("*.xhtml"))


def _partial_epub(files: List[Path]) -> Optional[Path]:
    if not files:
        return None
    handle = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
    handle.close()
    target = Path(handle.name)
    with zipfile.ZipFile(target, "w") as archive:
        for path in files:
            archive.write(path, arcname=f"OEBPS/xhtml/{path.name}")
    return target


def _metrics(source_text: str, target_text: str) -> Dict[str, Any]:
    metrics = audit_book._text_metrics(source_text, target_text)
    return {
        "pt_pt_per_100k": metrics.get("pt_pt_per_100k"),
        "english_leakage": metrics.get("english_leakage"),
        "repetition_ratio": metrics.get("repetition_ratio"),
        "length_ratio": metrics.get("length_ratio"),
        "target_words": metrics.get("target_words"),
    }


def audit(
    book_id: int,
    translation_id: str,
    samples_limit: int = 5,
) -> Dict[str, Any]:
    upload_dir = UPLOADS / translation_id
    source = _source_epub(upload_dir)
    targets = _target_files(upload_dir)
    if not source or not targets:
        return {
            "ok": False,
            "error": "source EPUB or translated XHTML files not found",
            "translation_id": translation_id,
            "book_id": book_id,
        }

    partial = _partial_epub(targets)
    try:
        source_text, source_files = audit_book._epub_text(source)
        target_text, target_files = audit_book._epub_text(partial)
    finally:
        if partial and partial.exists():
            partial.unlink()

    target_names = {name for name, _ in target_files}
    matched_source = [
        (name, paragraphs)
        for name, paragraphs in source_files
        if name in target_names
    ]
    if matched_source:
        source_text = "\n\n".join(
            paragraph for _, paragraphs in matched_source for paragraph in paragraphs
        )
    target_text = "\n\n".join(
        paragraph for _, paragraphs in target_files for paragraph in paragraphs
    )

    samples = audit_book._sample_pairs(
        matched_source or source_files,
        target_files,
        limit=samples_limit,
    )
    metrics = _metrics(source_text, target_text)

    book = QueueStore.get_book_readonly(str(QUEUE_DB), book_id)
    if book is None:
        return {
            "ok": False,
            "error": f"book {book_id} not found",
            "translation_id": translation_id,
        }
    glossary = COMPILED / f"{_slug(book.title)}-glossary.json"
    terms = audit_book._term_audit(
        book,
        source_text,
        target_text,
        glossary_path=glossary if glossary.exists() else None,
    )
    glossary_hash = None
    if glossary.exists():
        glossary_hash = hashlib.sha256(glossary.read_bytes()).hexdigest()
        (COMPILED / f"{_slug(book.title)}-glossary.sha256").write_text(
            glossary_hash + "\n",
            encoding="utf-8",
        )

    reasons: List[str] = []
    if not samples:
        reasons.append("no aligned source/target samples")
    if terms.get("error"):
        reasons.append(f"glossary audit failed: {terms['error']}")
    if terms.get("coverage") is not None and terms["coverage"] < 0.90:
        reasons.append(f"glossary coverage {terms['coverage']} < 0.90")
    if terms.get("forbidden_hits"):
        reasons.append(f"{len(terms['forbidden_hits'])} forbidden rendering(s)")
    if metrics.get("pt_pt_per_100k") is not None and metrics["pt_pt_per_100k"] > 50:
        reasons.append(f"pt-PT markers {metrics['pt_pt_per_100k']} > 50")
    if metrics.get("english_leakage") is not None and metrics["english_leakage"] > 0.01:
        reasons.append(f"English leakage {metrics['english_leakage']} > 0.01")
    if metrics.get("repetition_ratio") is not None and metrics["repetition_ratio"] > 0.05:
        reasons.append(f"repetition {metrics['repetition_ratio']} > 0.05")
    if metrics.get("length_ratio") is not None and not 0.80 <= metrics["length_ratio"] <= 1.20:
        reasons.append(f"length ratio {metrics['length_ratio']} outside 0.80-1.20")

    passed = not reasons
    report = {
        "ok": True,
        "passed": passed,
        "generated_at": _now(),
        "book_id": book_id,
        "title": book.title,
        "translation_id": translation_id,
        "scope": "partial",
        "files": len(targets),
        "samples": samples,
        "metrics": metrics,
        "terms": terms,
        "glossary": str(glossary) if glossary.exists() else None,
        "glossary_hash": glossary_hash,
        "reasons": reasons,
    }
    return report


def _write_report(report: Dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    slug = _slug(str(report.get("title") or "book"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPORTS / f"{slug}-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = path.with_suffix(".md")
    lines = [
        f"# Intra-run audit: {report.get('title')}",
        "",
        f"- Generated: {report.get('generated_at')}",
        f"- Scope: partial ({report.get('files')} XHTML files)",
        f"- Passed: {report.get('passed')}",
        f"- Glossary: {report.get('glossary')}",
        f"- Glossary hash: {report.get('glossary_hash')}",
        "",
        "## Metrics",
        "",
        json.dumps(report.get("metrics"), ensure_ascii=False, indent=2),
        "",
        "## Glossary",
        "",
        json.dumps(
            {
                "coverage": (report.get("terms") or {}).get("coverage"),
                "eligible": (report.get("terms") or {}).get("eligible"),
                "hits": (report.get("terms") or {}).get("hits"),
                "forbidden_hits": (report.get("terms") or {}).get("forbidden_hits"),
                "drift": (report.get("terms") or {}).get("drift"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "## Reasons",
        "",
        *(f"- {reason}" for reason in (report.get("reasons") or [])),
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-id", type=int, default=0)
    parser.add_argument("--translation-id", default="")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    health = _read_health()
    book_id = args.book_id or int(health.get("book_id") or 0)
    translation_id = args.translation_id or str(health.get("translation_id") or "")
    if not book_id:
        active = _active_book()
        if active:
            book_id = int(active["id"])
    if not translation_id:
        translation_id = str(health.get("translation_id") or "")
    if not book_id or not translation_id:
        print(json.dumps({"ok": False, "error": "no active book/translation"}, ensure_ascii=False))
        return 1

    report = audit(book_id, translation_id, samples_limit=args.samples)
    if report.get("ok"):
        path = _write_report(report)
        report["report"] = str(path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") and report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
