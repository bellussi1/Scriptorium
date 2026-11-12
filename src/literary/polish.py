"""Post-process completed Sun Eater artifacts with the reader repair pass.

The queue runner integrates the reader pass for new runs, but a run started
before that integration still produces plain refined artifacts.  This module is
the batch bridge: it walks completed Sun Eater books, applies the deterministic
reader repair, validates the result, records a quality sidecar and optionally
rebuilds the Kindle library.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .epub import validate_epub_structure
from .kindle import best_artifact, build_kindle_library
from .queue import QueueStore
from .queue_insights import (
    epub_metrics,
    find_report,
    quality_sidecar_path,
    read_json,
)
from .queue_runner import _epubcheck, _is_sun_eater
from .reading_repair import repair_reading_epub


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _already_polished(artifact: Path, report_path: Optional[Path], sidecar: Path) -> bool:
    if sidecar.is_file():
        payload = read_json(sidecar)
        repair = payload.get("reader_repair") or {}
        if repair.get("accepted") and sidecar.stat().st_mtime >= artifact.stat().st_mtime:
            return True
    if report_path is not None and report_path.is_file():
        report = read_json(report_path)
        repair = report.get("reader_repair") or {}
        if repair.get("accepted") and report_path.stat().st_mtime >= artifact.stat().st_mtime:
            return True
    return False


def polish_book(
    book: Any,
    outputs_dir: str | Path = "translated_files",
    *,
    force: bool = False,
    run_epubcheck: bool = True,
) -> Dict[str, Any]:
    outputs = Path(outputs_dir)
    artifact = best_artifact(outputs, book.title)
    if artifact is None:
        return {"title": book.title, "status": "skipped", "reason": "no artifact"}

    report_path = find_report(book.title)
    sidecar = quality_sidecar_path(artifact)
    if not force and _already_polished(artifact, report_path, sidecar):
        return {"title": book.title, "status": "skipped", "reason": "already polished"}

    temp = outputs / f".{artifact.stem}.polish.tmp.epub"
    if temp.exists():
        temp.unlink()
    try:
        repair = repair_reading_epub(
            str(artifact), str(temp), apply_terms=True, queue_title=book.title
        )
        issues = validate_epub_structure(str(temp))
        blocking = [
            issue.to_dict()
            for issue in issues
            if issue.severity.value in {"error", "critical"}
        ]
        check = _epubcheck(temp) if run_epubcheck else {}
        metrics = epub_metrics(temp)
        if blocking or (run_epubcheck and check.get("errors") != 0):
            return {
                "title": book.title,
                "status": "rejected",
                "reason": "reader validation gate failed",
                "blocking": blocking,
                "epubcheck": check,
            }

        os.replace(temp, artifact)
        repair["accepted"] = True
        payload = {
            "artifact": artifact.name,
            "size": artifact.stat().st_size,
            "sha256": _sha256(artifact),
            "reader_repair": repair,
            "epubcheck": check,
            "metrics": metrics.get("metrics", {}),
            "quality_flags": metrics.get("quality_flags", []),
            "polished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "title": book.title,
            "status": "polished",
            "artifact": str(artifact),
            "sidecar": str(sidecar),
            "merged": repair.get("merged"),
            "quote_paragraphs": repair.get("quote_paragraphs"),
            "quality_flags": payload["quality_flags"],
            "epubcheck": check,
        }
    except Exception as exc:
        return {"title": book.title, "status": "failed", "reason": str(exc)}
    finally:
        if temp.exists():
            temp.unlink()


def polish_completed_books(
    db_path: str = "data/literary_queue.db",
    outputs_dir: str | Path = "translated_files",
    *,
    book_id: int = 0,
    force: bool = False,
    run_epubcheck: bool = True,
    kindle_out: str = "",
) -> Dict[str, Any]:
    store = QueueStore(db_path)
    try:
        if book_id:
            book = store.get_book(book_id)
            books = [book] if book is not None else []
        else:
            books = store.list_books(status="completed", limit=500)
    finally:
        store.close()

    results: List[Dict[str, Any]] = []
    for book in books:
        if not _is_sun_eater(book):
            results.append({"title": book.title, "status": "skipped", "reason": "not Sun Eater"})
            continue
        results.append(
            polish_book(
                book,
                outputs_dir,
                force=force,
                run_epubcheck=run_epubcheck,
            )
        )

    kindle_result = None
    if kindle_out:
        kindle_result = build_kindle_library(
            db_path=db_path,
            outputs_dir=str(outputs_dir),
            output_root=kindle_out,
            include_needs_review=False,
        )
    return {
        "books": len(books),
        "polished": sum(1 for item in results if item.get("status") == "polished"),
        "skipped": sum(1 for item in results if item.get("status") == "skipped"),
        "rejected": sum(1 for item in results if item.get("status") == "rejected"),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "results": results,
        "kindle": kindle_result,
    }
