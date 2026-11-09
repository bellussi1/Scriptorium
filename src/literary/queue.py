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
from collections import deque
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

# Upstream checkpoint statuses -> queue editorial states. A completed upstream
# job still has to pass the literary validator before the queue calls it done.
UPSTREAM_STATE_MAP = {
    "running": "translating",
    "paused": "paused",
    "interrupted": "paused",
    "error": "failed",
    "partial": "needs_review",
    "completed": "validating",
}

# Deterministic preference for intermediate states. Without this, a set
# iteration could route "preparing -> validating" through "paused", which is
# semantically wrong for a job that is actually running.
TRANSITION_PREFERENCE = [
    "preparing",
    "translating",
    "reviewing",
    "validating",
    "completed",
    "needs_review",
    "paused",
    "failed",
    "pending",
]


def _ordered_transitions(state: str) -> List[str]:
    allowed = ALLOWED_TRANSITIONS.get(state, set())
    ordered = [candidate for candidate in TRANSITION_PREFERENCE if candidate in allowed]
    remainder = sorted(allowed - set(ordered))
    return ordered + remainder


def _transition_path(current: str, target: str, max_steps: int = 4) -> List[str]:
    """Find a deterministic short path through ALLOWED_TRANSITIONS."""
    if current == target:
        return [target]
    if current not in ALLOWED_TRANSITIONS:
        return []
    queue = deque([(current, [])])
    seen = {current}
    while queue:
        state, path = queue.popleft()
        if len(path) >= max_steps:
            continue
        for nxt in _ordered_transitions(state):
            if nxt == target:
                return path + [nxt]
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, path + [nxt]))
    return []


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
        # The queue lives on a Windows bind mount shared with the Docker app.
        # SQLite's WAL mode is not readable from the container's read-only
        # connection (the -shm file cannot be opened through that mount), so
        # use the rollback journal. Queue writes are infrequent enough that
        # this costs nothing measurable and keeps the web UI working.
        conn.execute("PRAGMA journal_mode = DELETE")
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
                    reviewed_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(calibre_id, source_hash, config_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_books_status ON books(status, priority DESC, id);
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    state TEXT NOT NULL DEFAULT 'pending',
                    translation_id TEXT NOT NULL DEFAULT '',
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
            # Migration for databases created before the upstream link existed.
            job_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(jobs)")
            }
            if "translation_id" not in job_columns:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN translation_id TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_translation_id "
                "ON jobs(translation_id) WHERE translation_id <> ''"
            )
            # Migration for queues created before the review gate existed.
            book_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(books)")
            }
            if "reviewed_at" not in book_columns:
                conn.execute(
                    "ALTER TABLE books ADD COLUMN reviewed_at TEXT NOT NULL DEFAULT ''"
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

    @classmethod
    def get_book_readonly(cls, db_path: str, book_id: int) -> Optional[QueueBook]:
        """Read one book without opening the database for writing.

        Planning and inspection must not take a write lock or run the WAL
        pragma while a translation is appending to the queue.
        """
        path = os.path.abspath(db_path)
        if not os.path.exists(path):
            return None
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        finally:
            conn.close()
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

    def mark_reviewed(self, book_id: int, message: str = "") -> bool:
        """Record that a human approved this book's translation."""
        now = utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE books SET reviewed_at = ?, updated_at = ? WHERE id = ?",
                (now, now, book_id),
            )
            if message:
                conn.execute(
                    "INSERT INTO events (book_id, level, message, created_at) "
                    "VALUES (?, 'info', ?, ?)",
                    (book_id, message, now),
                )
            conn.commit()
            return True

    def clear_reviewed(self, book_id: int) -> bool:
        """Invalidate a previous approval before a new translation starts."""
        now = utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE books SET reviewed_at = '', updated_at = ? WHERE id = ?",
                (now, book_id),
            )
            conn.commit()
            return True

    def update_book_model(self, book_id: int, model: str, provider: str) -> bool:
        """Set the model/provider a pending book should use on its next run."""
        model = (model or "").strip()
        provider = (provider or "").strip()
        if not model:
            raise ValueError("model is required")
        now = utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM books WHERE id = ?", (book_id,)
            ).fetchone()
            if not row:
                return False
            if row["status"] != "pending":
                raise ValueError("only pending books can change model")
            conn.execute(
                "UPDATE books SET model = ?, provider = ?, updated_at = ? WHERE id = ?",
                (model, provider, now, book_id),
            )
            conn.execute(
                "INSERT INTO events (book_id, level, message, created_at) "
                "VALUES (?, 'info', ?, ?)",
                (book_id, f"model -> {model} ({provider or 'default'})", now),
            )
            conn.commit()
            return True

    def next_pending_priority(self) -> int:
        """Priority that appends a new book after every pending entry."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(priority) FROM books WHERE status = 'pending'"
            ).fetchone()
        lowest = row[0] if row else None
        return (int(lowest) - 1) if lowest is not None else 0

    def move_book(self, book_id: int, direction: str) -> bool:
        """Move a pending book up/down in the queue and normalize priorities.

        Non-pending books keep the front of the list through a high priority
        band; pending books are renumbered in their chosen order.
        """
        if direction not in {"up", "down"}:
            raise ValueError("direction must be 'up' or 'down'")
        now = utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, status FROM books WHERE id = ?", (book_id,)
            ).fetchone()
            if not row:
                return False
            if row["status"] != "pending":
                raise ValueError("only pending books can be reordered")

            pending = conn.execute(
                """
                SELECT id FROM books
                WHERE status = 'pending'
                ORDER BY priority DESC, series, COALESCE(series_index, 0), id
                """
            ).fetchall()
            ids = [item["id"] for item in pending]
            index = ids.index(book_id)
            neighbour = index - 1 if direction == "up" else index + 1
            if neighbour < 0 or neighbour >= len(ids):
                return False
            ids[index], ids[neighbour] = ids[neighbour], ids[index]

            active = conn.execute(
                """
                SELECT id FROM books
                WHERE status <> 'pending'
                ORDER BY priority DESC, series, COALESCE(series_index, 0), id
                """
            ).fetchall()
            base = 1_000_000
            for offset, item in enumerate(active):
                conn.execute(
                    "UPDATE books SET priority = ?, updated_at = ? WHERE id = ?",
                    (base - offset, now, item["id"]),
                )
            for offset, item_id in enumerate(ids):
                conn.execute(
                    "UPDATE books SET priority = ?, updated_at = ? WHERE id = ?",
                    (len(ids) - offset, now, item_id),
                )
            conn.execute(
                "INSERT INTO events (book_id, level, message, created_at) "
                "VALUES (?, 'info', ?, ?)",
                (book_id, f"queue order changed: moved {direction}", now),
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

    def attach_translation_id(self, job_id: int, translation_id: str) -> bool:
        """Link a queue job to the upstream ``translation_id`` (idempotent)."""
        translation_id = (translation_id or "").strip()
        if not translation_id:
            raise ValueError("translation_id is required")
        now = utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT translation_id FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return False
            existing = (row["translation_id"] or "").strip()
            if existing and existing != translation_id:
                raise ValueError(
                    f"Job {job_id} is already linked to {existing}"
                )
            conflict = conn.execute(
                "SELECT id FROM jobs WHERE translation_id = ? AND id <> ?",
                (translation_id, job_id),
            ).fetchone()
            if conflict:
                raise ValueError(
                    f"translation_id {translation_id} is already linked to job {conflict['id']}"
                )
            conn.execute(
                "UPDATE jobs SET translation_id = ?, updated_at = ? WHERE id = ?",
                (translation_id, now, job_id),
            )
            book_id = conn.execute(
                "SELECT book_id FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()["book_id"]
            conn.execute(
                "INSERT INTO events (book_id, job_id, level, message, created_at) "
                "VALUES (?, ?, 'info', ?, ?)",
                (book_id, job_id, f"linked to upstream translation_id {translation_id}", now),
            )
            conn.commit()
            return True

    def get_job_by_translation_id(self, translation_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE translation_id = ?",
                ((translation_id or "").strip(),),
            ).fetchone()
            return dict(row) if row else None

    def list_jobs(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT j.*, b.title AS book_title, b.author, b.series, b.series_index
                FROM jobs j
                JOIN books b ON b.id = j.book_id
                ORDER BY j.id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def sync_from_upstream(self, checkpoint_db_path: str = "data/jobs.db") -> Dict[str, Any]:
        """Reconcile queue jobs with the upstream checkpoint database.

        Read-only on the upstream side. The upstream ``translation_jobs`` table
        is the authority for status and chunk counts; the queue keeps its own
        editorial states and chapter rows. Completed upstream jobs move to
        ``validating`` so a validator can decide between ``completed`` and
        ``needs_review``.
        """
        path = os.path.abspath(checkpoint_db_path)
        report: Dict[str, Any] = {
            "checkpoint_db": path,
            "checked": 0,
            "matched": 0,
            "updated": 0,
            "unmatched": [],
            "error": "",
        }
        if not os.path.exists(path):
            report["error"] = "checkpoint database not found"
            return report

        upstream = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        upstream.row_factory = sqlite3.Row
        try:
            rows = upstream.execute(
                "SELECT translation_id, status, progress, updated_at "
                "FROM translation_jobs ORDER BY updated_at DESC"
            ).fetchall()
        except sqlite3.Error as exc:
            report["error"] = str(exc)
            return report
        finally:
            upstream.close()

        now = utc_now()
        with self._lock, self._connect() as conn:
            for row in rows:
                report["checked"] += 1
                translation_id = row["translation_id"]
                job = conn.execute(
                    "SELECT * FROM jobs WHERE translation_id = ?",
                    (translation_id,),
                ).fetchone()
                if not job:
                    report["unmatched"].append(translation_id)
                    continue
                report["matched"] += 1

                latest = conn.execute(
                    "SELECT MAX(id) FROM jobs WHERE book_id = ?", (job["book_id"],)
                ).fetchone()[0]
                if int(job["id"]) != int(latest):
                    continue

                # Editorial review is a human decision. Once a job is
                # needs_review/completed, a stale upstream row (the CLI often
                # leaves "interrupted" after a complete run) must not pull it
                # backwards to paused/translating.
                if job["state"] in {"needs_review", "completed"}:
                    continue

                progress = json.loads(row["progress"] or "{}")
                current_chapter = int(
                    progress.get("completed_chunks")
                    if progress.get("completed_chunks") is not None
                    else job["current_chapter"] or 0
                )
                total_chapters = int(
                    progress.get("total_chunks")
                    if progress.get("total_chunks") is not None
                    else job["total_chapters"] or 0
                )
                # The CLI can exit after a full run without flipping the
                # upstream row to completed. Infer completion from progress
                # instead of leaving the queue stuck in "translating".
                effective_status = row["status"]
                if (
                    total_chapters > 0
                    and current_chapter >= total_chapters
                    and not progress.get("failed_chunks")
                ):
                    effective_status = "completed"
                elif (
                    effective_status == "running"
                    and total_chapters > 0
                    and current_chapter >= total_chapters
                ):
                    effective_status = "partial"
                target_state = UPSTREAM_STATE_MAP.get(
                    effective_status, "needs_review"
                )
                checkpoint = json.loads(job["checkpoint_json"] or "{}")
                upstream_payload = {
                    "upstream_status": row["status"],
                    "upstream_effective_status": effective_status,
                    "upstream_current_chunk": progress.get("current_chunk_index"),
                    "upstream_total_chunks": progress.get("total_chunks"),
                    "upstream_completed_chunks": progress.get("completed_chunks"),
                    "upstream_failed_chunks": progress.get("failed_chunks"),
                    "upstream_updated_at": row["updated_at"],
                }

                state_changed = self._sync_job_state(
                    conn,
                    job,
                    target_state,
                    now,
                    f"sync: upstream {row['status']} -> {effective_status} "
                    f"({current_chapter}/{total_chapters} chunks)",
                )
                book = conn.execute(
                    "SELECT status FROM books WHERE id = ?", (job["book_id"],)
                ).fetchone()
                book_changed = False
                if book and book["status"] != target_state:
                    if book["status"] == "completed":
                        conn.execute(
                            "INSERT INTO events (book_id, job_id, level, message, created_at) "
                            "VALUES (?, ?, 'warning', ?, ?)",
                            (
                                job["book_id"],
                                job["id"],
                                f"sync ignored: completed book cannot return to {target_state}",
                                now,
                            ),
                        )
                    else:
                        conn.execute(
                            "UPDATE books SET status = ?, updated_at = ? WHERE id = ?",
                            (target_state, now, job["book_id"]),
                        )
                        conn.execute(
                            "INSERT INTO events (book_id, job_id, level, message, created_at) "
                            "VALUES (?, ?, 'info', ?, ?)",
                            (
                                job["book_id"],
                                job["id"],
                                f"book state -> {target_state}: sync",
                                now,
                            ),
                        )
                        book_changed = True

                progress_changed = (
                    job["current_chapter"] != current_chapter
                    or job["total_chapters"] != total_chapters
                    or any(
                        checkpoint.get(key) != value
                        for key, value in upstream_payload.items()
                    )
                )
                checkpoint.update(upstream_payload)
                checkpoint["last_sync_at"] = now
                serialized_checkpoint = json.dumps(checkpoint, ensure_ascii=False)
                conn.execute(
                    "UPDATE jobs SET current_chapter = ?, total_chapters = ?, "
                    "checkpoint_json = ?, updated_at = ? WHERE id = ?",
                    (
                        current_chapter,
                        total_chapters,
                        serialized_checkpoint,
                        now,
                        job["id"],
                    ),
                )
                if state_changed or book_changed or progress_changed:
                    report["updated"] += 1
            conn.commit()
        return report

    def _sync_job_state(
        self,
        conn: sqlite3.Connection,
        job: sqlite3.Row,
        target: str,
        now: str,
        message: str,
    ) -> bool:
        current = job["state"]
        if current == target:
            return False
        if current == "completed":
            conn.execute(
                "INSERT INTO events (book_id, job_id, level, message, created_at) "
                "VALUES (?, ?, 'warning', ?, ?)",
                (
                    job["book_id"],
                    job["id"],
                    f"sync ignored: completed job cannot return to {target}",
                    now,
                ),
            )
            return False
        path = _transition_path(current, target)
        if not path:
            path = [target]
            message += " (forced transition)"
        for state in path:
            conn.execute(
                "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
                (state, now, job["id"]),
            )
            conn.execute(
                "INSERT INTO events (book_id, job_id, level, message, created_at) "
                "VALUES (?, ?, 'info', ?, ?)",
                (job["book_id"], job["id"], f"state -> {state}: {message}", now),
            )
        return True

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def latest_job(self, book_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE book_id = ? ORDER BY id DESC LIMIT 1",
                (book_id,),
            ).fetchone()
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

    def add_event(
        self,
        message: str,
        *,
        book_id: Optional[int] = None,
        job_id: Optional[int] = None,
        level: str = "info",
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO events (book_id, job_id, level, message, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (book_id, job_id, level, message, now),
            )
            conn.commit()

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
