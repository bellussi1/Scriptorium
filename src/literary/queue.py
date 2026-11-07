"""Persistent book queue and chapter checkpoints.

This is deliberately separate from the upstream ``data/jobs.db``. The upstream
job store tracks one file translation; this store tracks a book across
planning, preparation, translation, review and validation, and survives server
restarts without holding any book text.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .models import BookRecord, QueueBook, QueueChapter, utc_now

STATES = {
    "pending",
    "preparing",
    "translating",
    "reviewing",
    "validating",
    "completed",
    "paused",
    "failed",
    "needs_review",
}
TERMINAL_STATES = {"completed"}

ALLOWED_TRANSITIONS = {
    "pending": {"preparing", "paused", "failed"},
    "preparing": {"translating", "paused", "failed", "needs_review"},
    "translating": {"reviewing", "validating", "paused", "failed", "needs_review"},
    "reviewing": {"validating", "paused", "failed", "needs_review"},
    "validating": {"completed", "paused", "failed", "needs_review"},
    "paused": {"preparing", "translating", "reviewing", "validating", "pending", "failed"},
    "failed": {"pending", "preparing", "translating", "paused"},
    "needs_review": {"reviewing", "validating", "translating", "paused", "completed"},
    "completed": set(),
}


def hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_config(config: Dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class QueueStore:
    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    calibre_id INTEGER NOT NULL,
                    source_path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT '',
                    series TEXT NOT NULL DEFAULT '',
                    series_index REAL,
                    source_language TEXT NOT NULL DEFAULT '',
                    target_language TEXT NOT NULL DEFAULT 'pt-BR',
                    word_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority INTEGER NOT NULL DEFAULT 0,
                    glossary_scope TEXT NOT NULL DEFAULT '',
                    style_scope TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    actual_cost REAL NOT NULL DEFAULT 0,
                    source_hash TEXT NOT NULL DEFAULT '',
                    config_hash TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(calibre_id, source_hash, config_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_books_status ON books(status, priority DESC, id);
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    state TEXT NOT NULL DEFAULT 'pending',
                    current_chapter INTEGER NOT NULL DEFAULT 0,
                    total_chapters INTEGER NOT NULL DEFAULT 0,
                    checkpoint_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_book ON jobs(book_id, id);
                CREATE TABLE IF NOT EXISTS chapters (
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    chapter_index INTEGER NOT NULL,
                    href TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    source_hash TEXT NOT NULL DEFAULT '',
                    translated_hash TEXT NOT NULL DEFAULT '',
                    tokens_in INTEGER NOT NULL DEFAULT 0,
                    tokens_out INTEGER NOT NULL DEFAULT 0,
                    cost REAL NOT NULL DEFAULT 0,
                    validation_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, chapter_index)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER,
                    job_id INTEGER,
                    level TEXT NOT NULL DEFAULT 'info',
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def _assert_state(self, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"Unknown queue state: {state}")

    def add_book(
        self,
        record: BookRecord,
        *,
        target_language: str = "pt-BR",
        priority: int = 0,
        glossary_scope: str = "",
        style_scope: str = "",
        model: str = "",
        provider: str = "",
        estimated_cost: float = 0.0,
        config: Optional[Dict[str, Any]] = None,
    ) -> int:
        source_hash = hash_file(record.epub_path) if record.epub_path and os.path.exists(record.epub_path) else ""
        config_hash = hash_config(config or {"model": model, "provider": provider, "glossary": glossary_scope, "style": style_scope})
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO books (
                    calibre_id, source_path, title, author, series, series_index,
                    source_language, target_language, word_count, status, priority,
                    glossary_scope, style_scope, model, provider, estimated_cost,
                    source_hash, config_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(calibre_id, source_hash, config_hash) DO UPDATE SET
                    title = excluded.title,
                    author = excluded.author,
                    series = excluded.series,
                    series_index = excluded.series_index,
                    word_count = excluded.word_count,
                    priority = excluded.priority,
                    glossary_scope = excluded.glossary_scope,
                    style_scope = excluded.style_scope,
                    model = excluded.model,
                    provider = excluded.provider,
                    estimated_cost = excluded.estimated_cost,
                    updated_at = excluded.updated_at
                """,
                (
                    record.calibre_id,
                    record.epub_path or "",
                    record.title,
                    record.author,
                    record.series,
                    record.series_index,
                    (record.languages[0] if record.languages else ""),
                    target_language,
                    record.word_count,
                    priority,
                    glossary_scope,
                    style_scope,
                    model,
                    provider,
                    estimated_cost,
                    source_hash,
                    config_hash,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM books WHERE calibre_id = ? AND source_hash = ? AND config_hash = ?",
                (record.calibre_id, source_hash, config_hash),
            ).fetchone()
            book_id = int(row["id"])
            conn.execute(
                "INSERT INTO events (book_id, level, message, created_at) VALUES (?, 'info', ?, ?)",
                (book_id, "book enqueued", now),
            )
            conn.commit()
            return book_id

    def get_book(self, book_id: int) -> Optional[QueueBook]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            return QueueBook(**dict(row)) if row else None

    def list_books(self, status: Optional[str] = None, limit: int = 200) -> List[QueueBook]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    """SELECT * FROM books WHERE status = ?
                       ORDER BY priority DESC, series, COALESCE(series_index, 0), id LIMIT ?""",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM books
                       ORDER BY priority DESC, series, COALESCE(series_index, 0), id LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [QueueBook(**dict(row)) for row in rows]

    def set_book_state(self, book_id: int, state: str, message: str = "") -> bool:
        self._assert_state(state)
        now = utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT status FROM books WHERE id = ?", (book_id,)).fetchone()
            if not row:
                return False
            current = row["status"]
            if current != state and state not in ALLOWED_TRANSITIONS.get(current, set()):
                raise ValueError(f"Invalid transition for book {book_id}: {current} -> {state}")
            conn.execute(
                "UPDATE books SET status = ?, updated_at = ? WHERE id = ?", (state, now, book_id)
            )
            conn.execute(
                "INSERT INTO events (book_id, level, message, created_at) VALUES (?, 'info', ?, ?)",
                (book_id, message or f"state -> {state}", now),
            )
            conn.commit()
            return True

    def create_job(self, book_id: int, total_chapters: int = 0) -> int:
        now = utc_now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO jobs (book_id, state, total_chapters, created_at, updated_at) VALUES (?, 'pending', ?, ?, ?)",
                (book_id, total_chapters, now, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def set_job_state(self, job_id: int, state: str, error: str = "", checkpoint: Optional[Dict[str, Any]] = None) -> bool:
        self._assert_state(state)
        now = utc_now()
        with self._lock, self._connect() as conn:
            current = conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not current:
                return False
            if current["state"] != state and state not in ALLOWED_TRANSITIONS.get(current["state"], set()):
                raise ValueError(f"Invalid transition for job {job_id}: {current['state']} -> {state}")
            fields = ["state = ?", "error = ?", "updated_at = ?"]
            values: List[Any] = [state, error, now]
            if checkpoint is not None:
                fields.append("checkpoint_json = ?")
                values.append(json.dumps(checkpoint, ensure_ascii=False))
            values.append(job_id)
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
            return True

    def record_chapter(
        self,
        job_id: int,
        chapter_index: int,
        *,
        href: str = "",
        title: str = "",
        status: str = "pending",
        source_hash: str = "",
        translated_hash: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
        validation: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chapters (
                    job_id, chapter_index, href, title, status, source_hash, translated_hash,
                    tokens_in, tokens_out, cost, validation_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, chapter_index) DO UPDATE SET
                    href = excluded.href,
                    title = excluded.title,
                    status = excluded.status,
                    source_hash = excluded.source_hash,
                    translated_hash = excluded.translated_hash,
                    tokens_in = excluded.tokens_in,
                    tokens_out = excluded.tokens_out,
                    cost = excluded.cost,
                    validation_json = excluded.validation_json,
                    updated_at = excluded.updated_at
                """,
                (
                    job_id,
                    chapter_index,
                    href,
                    title,
                    status,
                    source_hash,
                    translated_hash,
                    tokens_in,
                    tokens_out,
                    cost,
                    json.dumps(validation or {}, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()

    def list_chapters(self, job_id: int) -> List[QueueChapter]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE job_id = ? ORDER BY chapter_index", (job_id,)
            ).fetchall()
            return [QueueChapter(**dict(row)) for row in rows]

    def next_pending(self) -> Optional[QueueBook]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM books WHERE status = 'pending'
                   ORDER BY priority DESC, series, COALESCE(series_index, 0), id LIMIT 1"""
            ).fetchone()
            return QueueBook(**dict(row)) if row else None

    def reset_in_progress(self) -> int:
        """On startup, make interrupted work resumable instead of pretending it is running."""
        now = utc_now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE books SET status = 'paused', updated_at = ? WHERE status IN ('preparing','translating','reviewing','validating')",
                (now,),
            )
            cur2 = conn.execute(
                "UPDATE jobs SET state = 'paused', updated_at = ? WHERE state IN ('preparing','translating','reviewing','validating')",
                (now,),
            )
            conn.commit()
            return int(cur.rowcount or 0) + int(cur2.rowcount or 0)

    def summary(self) -> Dict[str, Any]:
        with self._connect() as conn:
            counts = {row["status"]: row["n"] for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM books GROUP BY status"
            )}
            totals = conn.execute(
                "SELECT COUNT(*) AS books, COALESCE(SUM(word_count),0) AS words, COALESCE(SUM(actual_cost),0) AS cost FROM books"
            ).fetchone()
            return {
                "books": int(totals["books"]),
                "words": int(totals["words"]),
                "actual_cost": round(float(totals["cost"]), 4),
                "by_status": counts,
            }

    def events(self, book_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            if book_id is None:
                rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE book_id = ? ORDER BY id DESC LIMIT ?", (book_id, limit)
                ).fetchall()
            return [dict(row) for row in rows]

    def close(self) -> None:
        # SQLite connections are per-operation; nothing to keep open.
        return None
