"""Read-only JSON view of the persistent literary queue.

The queue database is written by the CLI/wrapper in ``src/literary/queue.py``.
This endpoint only reads it; it never starts, pauses or mutates a job.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, jsonify


def _db_path() -> Path:
    return Path(os.getenv("LITERARY_QUEUE_DB", "data/literary_queue.db"))


def build_queue_snapshot(db_path: str | Path) -> Dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {
            "status": "empty",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": {"books": 0, "words": 0, "by_status": {}},
            "books": [],
            "events": [],
        }

    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        books = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    b.id, b.calibre_id, b.title, b.author, b.series,
                    b.series_index, b.status, b.word_count, b.model, b.provider,
                    j.id AS job_id, j.state AS job_state, j.translation_id,
                    j.current_chapter, j.total_chapters, j.error,
                    j.updated_at AS job_updated_at
                FROM books b
                LEFT JOIN jobs j
                    ON j.id = (SELECT MAX(id) FROM jobs WHERE book_id = b.id)
                ORDER BY b.priority DESC, b.series, COALESCE(b.series_index, 0), b.id
                """
            )
        ]
        events = [
            dict(row)
            for row in conn.execute(
                "SELECT level, message, created_at FROM events "
                "ORDER BY id DESC LIMIT 10"
            )
        ]
    finally:
        conn.close()

    by_status: Dict[str, int] = {}
    for book in books:
        state = book.get("job_state") or book.get("status") or "pending"
        by_status[state] = by_status.get(state, 0) + 1

    return {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "books": len(books),
            "words": sum(int(book.get("word_count") or 0) for book in books),
            "by_status": by_status,
        },
        "books": books,
        "events": events,
    }


def create_literary_queue_blueprint() -> Blueprint:
    bp = Blueprint("literary_queue", __name__)

    @bp.route("/api/literary/queue", methods=["GET"])
    def get_literary_queue():
        try:
            return jsonify(build_queue_snapshot(_db_path()))
        except Exception as exc:  # pragma: no cover - defensive boundary
            return (
                jsonify(
                    {
                        "status": "error",
                        "error": str(exc),
                        "books": [],
                        "events": [],
                        "summary": {"books": 0, "words": 0, "by_status": {}},
                    }
                ),
                500,
            )

    return bp
