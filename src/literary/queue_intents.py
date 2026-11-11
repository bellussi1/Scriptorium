"""Single writer for ``literary_queue.db``: intent spool, ingest and apply.

The Flask app runs in a container and must not write the queue database: its
SQLite locks do not coordinate with host processes across the Docker bind
mount. Instead the app records every change as one spool file next to the
database (``literary_queue.intents/``). The host runner calls :func:`drain`,
which ingests the spool into the ``queue_intents`` table and applies pending
rows in id order, one transaction per intent. The UI reads results with
:func:`read_intent`.

Design: ``docs/project/reviews/single-writer-design-2026-11-11.md``.

Run once by hand::

    python -m src.literary.queue_intents --db data/literary_queue.db --once
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.literary.models import utc_now
from src.literary.queue import ALLOWED_TRANSITIONS, QueueStore, _transition_path

logger = logging.getLogger(__name__)

KINDS = ("add", "approve", "retry", "move", "remove", "update_model", "event")
ACTIVE_STATES = {"preparing", "translating", "reviewing", "validating"}
TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
BUSY_TIMEOUT_MS = 30_000
SPOOL_ORDER = 20  # digits of the time.time_ns() prefix in spool file names

SCHEMA = """
CREATE TABLE IF NOT EXISTS queue_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    error_status INTEGER NOT NULL DEFAULT 0,
    result TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_queue_intents_pending
    ON queue_intents(applied_at, id);
"""


class IntentRefused(Exception):
    """A change that no longer makes sense for the current queue state."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def spool_dir(db_path: str | Path) -> Path:
    """Directory of pending intent files for one queue database."""
    path = Path(db_path)
    return path.with_name(f"{path.stem}.intents")


def _replace_with_retry(temporary: Path, final: Path, text: str) -> None:
    # Same approach as queue_run_control: Windows may briefly lock the target.
    last_error: Optional[PermissionError] = None
    for attempt in range(20):
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, final)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(min(0.05 * (attempt + 1), 0.5))
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
    raise last_error or PermissionError(f"could not write {final}")


def enqueue(db_path: str | Path, kind: str, payload: Dict[str, Any]) -> str:
    """Record one change for the host runner. Never touches the database.

    Returns the token the UI uses to read the result.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown intent kind: {kind}")
    token = uuid.uuid4().hex
    directory = spool_dir(db_path)
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():0{SPOOL_ORDER}d}-{token}.json"
    body = json.dumps(
        {"token": token, "kind": kind, "payload": payload, "created_at": utc_now()},
        ensure_ascii=False,
    )
    _replace_with_retry(directory / f".{name}.tmp", directory / name, body + "\n")
    return token


def _token_from_name(name: str) -> str:
    stem = name[: -len(".json")] if name.endswith(".json") else name
    return stem.split("-", 1)[1] if "-" in stem else stem


def _spool_files(directory: Path) -> List[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.suffix == ".json" and not path.name.startswith(".") and path.is_file()
    )


def _readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True, timeout=5
    )
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'queue_intents'"
    ).fetchone()
    return row is not None


def read_intent(db_path: str | Path, token: str) -> Optional[Dict[str, Any]]:
    """Read-only view of one intent for the UI.

    Returns ``state`` ``queued`` (spooled or pending) or ``applied`` (with
    ``error`` and ``error_status`` when refused). Returns ``None`` for a token
    the runner has never seen. Read errors report ``queued``: the UI keeps
    polling and the runner settles the state later.
    """
    if not TOKEN_PATTERN.match(token or ""):
        return None
    path = Path(db_path)
    row: Optional[sqlite3.Row] = None
    if path.exists():
        try:
            conn = _readonly(path)
            try:
                if _has_table(conn):
                    row = conn.execute(
                        "SELECT token, kind, created_at, applied_at, error, "
                        "error_status, result FROM queue_intents WHERE token = ?",
                        (token,),
                    ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return {"token": token, "state": "queued"}
    if row is not None:
        applied = bool(row["applied_at"])
        return {
            "token": token,
            "kind": row["kind"],
            "state": "applied" if applied else "queued",
            "created_at": row["created_at"],
            "applied_at": row["applied_at"],
            "error": row["error"],
            "error_status": int(row["error_status"] or 0),
            "result": json.loads(row["result"] or "{}"),
        }
    for name_path in _spool_files(spool_dir(path)):
        if _token_from_name(name_path.name) == token:
            return {"token": token, "state": "queued"}
    return None


def pending_summary(db_path: str | Path) -> Dict[str, Any]:
    """Counts for the snapshot: intents waiting for the host runner."""
    path = Path(db_path)
    spooled = len(_spool_files(spool_dir(path)))
    pending = 0
    oldest: Optional[str] = None
    if path.exists():
        try:
            conn = _readonly(path)
            try:
                if _has_table(conn):
                    row = conn.execute(
                        "SELECT COUNT(*) AS n, MIN(created_at) AS oldest "
                        "FROM queue_intents WHERE applied_at = ''"
                    ).fetchone()
                    pending = int(row["n"] or 0)
                    oldest = row["oldest"] or None
            finally:
                conn.close()
        except sqlite3.Error:
            pass
    return {
        "pending": pending + spooled,
        "spooled": spooled,
        "oldest_pending_at": oldest,
    }


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Host-side connection: rollback journal, busy timeout, FK cascades."""
    conn = sqlite3.connect(
        str(db_path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = DELETE")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Additive migration: create the intent table if it is missing."""
    conn.executescript(SCHEMA)


def _is_transient(exc: sqlite3.Error) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _ingest_spool(conn: sqlite3.Connection, directory: Path) -> int:
    files = _spool_files(directory)
    if not files:
        return 0
    now = utc_now()
    rows = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        token = _token_from_name(path.name)
        if (
            isinstance(data, dict)
            and data.get("kind") in KINDS
            and isinstance(data.get("payload"), dict)
            and TOKEN_PATTERN.match(str(data.get("token") or ""))
        ):
            rows.append(
                (
                    str(data["token"]),
                    data["kind"],
                    json.dumps(data["payload"], ensure_ascii=False),
                    str(data.get("created_at") or now),
                    "",
                    "",
                    0,
                )
            )
        else:
            # Refused at ingest: visible to the UI, never applied.
            rows.append(
                (
                    token,
                    "malformed",
                    "{}",
                    now,
                    now,
                    f"malformed intent file {path.name}",
                    400,
                )
            )
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO queue_intents "
            "(token, kind, payload, created_at, applied_at, error, error_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute("COMMIT")
    except sqlite3.Error:
        _rollback(conn)
        raise
    # Delete only after the commit: a crash here re-ingests as a no-op.
    for path in files:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return len(files)


# --- apply handlers --------------------------------------------------------
# Each handler mirrors the rules the routes used to enforce and performs the
# same statements the QueueStore methods performed, inside one transaction.


def _book(conn: sqlite3.Connection, book_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise IntentRefused("book not found", 404)
    return row


def _latest_job(conn: sqlite3.Connection, book_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM jobs WHERE book_id = ? ORDER BY id DESC LIMIT 1", (book_id,)
    ).fetchone()


def _event(
    conn: sqlite3.Connection,
    message: str,
    *,
    book_id: Optional[int],
    job_id: Optional[int] = None,
    now: str,
) -> None:
    conn.execute(
        "INSERT INTO events (book_id, job_id, level, message, created_at) "
        "VALUES (?, ?, 'info', ?, ?)",
        (book_id, job_id, message, now),
    )


def _walk_book(
    conn: sqlite3.Connection, book_id: int, start: str, target: str, message: str, now: str
) -> None:
    for state in _transition_path(start, target):
        conn.execute(
            "UPDATE books SET status = ?, updated_at = ? WHERE id = ?", (state, now, book_id)
        )
        _event(conn, message or f"state -> {state}", book_id=book_id, now=now)


def _walk_job(
    conn: sqlite3.Connection, job_id: int, start: str, target: str, message: str, now: str
) -> None:
    # The route passed the message as the job error text; kept for parity.
    for state in _transition_path(start, target):
        conn.execute(
            "UPDATE jobs SET state = ?, error = ?, updated_at = ? WHERE id = ?",
            (state, message, now, job_id),
        )


def _apply_add(conn: sqlite3.Connection, payload: Dict[str, Any], now: str) -> Dict[str, Any]:
    added: List[int] = []
    duplicates: List[int] = []
    model = str(payload.get("model") or "")
    provider = str(payload.get("provider") or "")
    for item in payload.get("books") or []:
        calibre_id = int(item["calibre_id"])
        exists = conn.execute(
            "SELECT id FROM books WHERE calibre_id = ? LIMIT 1", (calibre_id,)
        ).fetchone()
        if exists is not None:
            duplicates.append(calibre_id)
            continue
        lowest = conn.execute(
            "SELECT MIN(priority) FROM books WHERE status = 'pending'"
        ).fetchone()[0]
        priority = (int(lowest) - 1) if lowest is not None else 0
        languages = list(item.get("languages") or [])
        cursor = conn.execute(
            """
            INSERT INTO books (
                calibre_id, source_path, title, author, series, series_index,
                source_language, target_language, word_count, status, priority,
                glossary_scope, style_scope, model, provider, estimated_cost,
                source_hash, config_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, '', '', ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                calibre_id,
                str(item.get("epub_path") or ""),
                str(item.get("title") or ""),
                str(item.get("author") or ""),
                str(item.get("series") or ""),
                item.get("series_index"),
                (languages[0] if languages else ""),
                str(payload.get("target_language") or "pt-BR"),
                int(item.get("word_count") or 0),
                priority,
                model,
                provider,
                str(item.get("source_hash") or ""),
                str(item.get("config_hash") or ""),
                now,
                now,
            ),
        )
        book_id = int(cursor.lastrowid)
        _event(conn, "book enqueued", book_id=book_id, now=now)
        added.append(book_id)
    return {"added": added, "duplicates": duplicates}


def _apply_approve(conn: sqlite3.Connection, payload: Dict[str, Any], now: str) -> Dict[str, Any]:
    book_id = int(payload["book_id"])
    book = _book(conn, book_id)
    job = _latest_job(conn, book_id)
    unreviewed = not str(book["reviewed_at"] or "").strip()
    needs_review = book["status"] == "needs_review" or (
        job is not None and job["state"] == "needs_review"
    )
    if not needs_review and not unreviewed:
        raise IntentRefused("book does not need review", 409)
    message = "human review approved from Queue UI"
    if job is not None:
        _walk_job(conn, int(job["id"]), str(job["state"] or ""), "completed", message, now)
    _walk_book(conn, book_id, str(book["status"]), "completed", message, now)
    conn.execute(
        "UPDATE books SET reviewed_at = ?, updated_at = ? WHERE id = ?", (now, now, book_id)
    )
    _event(conn, message, book_id=book_id, now=now)
    _event(
        conn,
        message,
        book_id=book_id,
        job_id=int(job["id"]) if job is not None else None,
        now=now,
    )
    return {}


def _apply_retry(conn: sqlite3.Connection, payload: Dict[str, Any], now: str) -> Dict[str, Any]:
    book_id = int(payload["book_id"])
    book = _book(conn, book_id)
    if book["status"] not in {"failed", "needs_review", "paused"}:
        raise IntentRefused("only failed, paused or needs-review books can be retried", 409)
    job = _latest_job(conn, book_id)
    if job is not None and job["state"] in ACTIVE_STATES:
        raise IntentRefused("the translation job is still active", 409)
    message = (
        "resume requested from Queue UI"
        if book["status"] == "paused"
        else "retry requested from Queue UI"
    )
    conn.execute(
        "UPDATE books SET reviewed_at = '', updated_at = ? WHERE id = ?", (now, book_id)
    )
    if job is not None and bool(payload.get("release_stale_checkpoint")):
        conn.execute(
            """
            UPDATE jobs
            SET translation_id = '', current_chapter = 0, total_chapters = 0,
                checkpoint_json = '{}', error = '', updated_at = ?
            WHERE id = ?
            """,
            (now, int(job["id"])),
        )
        _event(
            conn,
            "stale checkpoint released before retry",
            book_id=book_id,
            job_id=int(job["id"]),
            now=now,
        )
    _walk_book(conn, book_id, str(book["status"]), "pending", message, now)
    _event(conn, message, book_id=book_id, now=now)
    return {}


def _apply_move(conn: sqlite3.Connection, payload: Dict[str, Any], now: str) -> Dict[str, Any]:
    book_id = int(payload["book_id"])
    direction = str(payload.get("direction") or "")
    if direction not in {"up", "down"}:
        raise IntentRefused("direction must be 'up' or 'down'", 400)
    row = conn.execute("SELECT id, status FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise IntentRefused("book not found", 404)
    if row["status"] != "pending":
        raise IntentRefused("only pending books can be reordered", 409)
    ids = [
        item["id"]
        for item in conn.execute(
            """
            SELECT id FROM books WHERE status = 'pending'
            ORDER BY priority DESC, series, COALESCE(series_index, 0), id
            """
        ).fetchall()
    ]
    index = ids.index(book_id)
    neighbour = index - 1 if direction == "up" else index + 1
    if neighbour < 0 or neighbour >= len(ids):
        raise IntentRefused("book is already at the edge of the queue", 409)
    ids[index], ids[neighbour] = ids[neighbour], ids[index]
    active = conn.execute(
        """
        SELECT id FROM books WHERE status <> 'pending'
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
    _event(conn, f"queue order changed: moved {direction}", book_id=book_id, now=now)
    return {"moved": {"book_id": book_id, "direction": direction}}


def _apply_remove(conn: sqlite3.Connection, payload: Dict[str, Any], now: str) -> Dict[str, Any]:
    book_id = int(payload["book_id"])
    book = _book(conn, book_id)
    job = _latest_job(conn, book_id)
    if book["status"] in ACTIVE_STATES or (job is not None and job["state"] in ACTIVE_STATES):
        raise IntentRefused("pause the book before removing it from the queue", 409)
    # Detach the book's history so no event refers to a deleted book.
    conn.execute("UPDATE events SET book_id = NULL WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    _event(conn, f"removed from queue: {book['title']}", book_id=None, now=now)
    return {"removed": {"book_id": book_id, "title": str(book["title"])}}


def _apply_update_model(
    conn: sqlite3.Connection, payload: Dict[str, Any], now: str
) -> Dict[str, Any]:
    book_id = int(payload["book_id"])
    model = str(payload.get("model") or "").strip()
    provider = str(payload.get("provider") or "").strip()
    if not model:
        raise IntentRefused("model is required", 400)
    row = conn.execute("SELECT status FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise IntentRefused("book not found", 404)
    if row["status"] != "pending":
        raise IntentRefused("only pending books can change model", 409)
    conn.execute(
        "UPDATE books SET model = ?, provider = ?, updated_at = ? WHERE id = ?",
        (model, provider, now, book_id),
    )
    _event(
        conn,
        f"model -> {model} ({provider or 'default'})",
        book_id=book_id,
        now=now,
    )
    return {"updated": {"book_id": book_id, "model": model, "provider": provider}}


def _apply_event(conn: sqlite3.Connection, payload: Dict[str, Any], now: str) -> Dict[str, Any]:
    book_id = payload.get("book_id")
    _event(
        conn,
        str(payload.get("message") or ""),
        book_id=int(book_id) if book_id is not None else None,
        now=now,
    )
    return {}


_HANDLERS: Dict[str, Callable[[sqlite3.Connection, Dict[str, Any], str], Dict[str, Any]]] = {
    "add": _apply_add,
    "approve": _apply_approve,
    "retry": _apply_retry,
    "move": _apply_move,
    "remove": _apply_remove,
    "update_model": _apply_update_model,
    "event": _apply_event,
}


def _record(conn: sqlite3.Connection, row_id: int, error: str, status: int) -> str:
    """Store a refusal or failure in its own short transaction."""
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if _is_transient(exc):
            return "deferred"
        raise
    conn.execute(
        "UPDATE queue_intents SET applied_at = ?, error = ?, error_status = ?, "
        "result = '{}' WHERE id = ?",
        (utc_now(), error, status, row_id),
    )
    conn.execute("COMMIT")
    return "refused" if status < 500 else "failed"


def _apply_row(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    """Apply one pending intent atomically. Returns the outcome label."""
    row_id = int(row["id"])
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if _is_transient(exc):
            return "deferred"
        raise
    try:
        payload = json.loads(row["payload"] or "{}")
        handler = _HANDLERS[str(row["kind"])]
        result = handler(conn, payload, utc_now())
        conn.execute(
            "UPDATE queue_intents SET applied_at = ?, error = '', error_status = 0, "
            "result = ? WHERE id = ?",
            (utc_now(), json.dumps(result, ensure_ascii=False), row_id),
        )
        conn.execute("COMMIT")
        return "applied"
    except IntentRefused as exc:
        _rollback(conn)
        return _record(conn, row_id, str(exc), exc.status)
    except sqlite3.Error as exc:
        _rollback(conn)
        if _is_transient(exc):
            return "deferred"
        logger.exception("queue intent %s failed", row_id)
        return _record(conn, row_id, f"internal error: {exc}", 500)
    except Exception as exc:  # a bad payload must not stall later intents
        _rollback(conn)
        logger.exception("queue intent %s failed", row_id)
        return _record(conn, row_id, f"internal error: {exc}", 500)


_PREPARED: set[str] = set()


def _prepare(db: Path) -> None:
    """Run the base and intent migrations once per process and database."""
    key = str(db.resolve())
    if key in _PREPARED:
        return
    if not db.exists():
        QueueStore(str(db)).close()  # first run on a fresh install
    conn = connect(db)
    try:
        ensure_schema(conn)
    finally:
        conn.close()
    _PREPARED.add(key)


def drain(db_path: str | Path, *, batch: int = 50) -> Dict[str, Any]:
    """Ingest the spool and apply pending intents in id order.

    Safe to call repeatedly. A transient lock stops the batch and reports
    ``deferred``; the next call resumes at the same intent.
    """
    db = Path(db_path)
    stats: Dict[str, Any] = {
        "ingested": 0,
        "applied": 0,
        "refused": 0,
        "failed": 0,
        "pending": 0,
        "deferred": False,
    }
    if not db.exists() and not spool_dir(db).is_dir():
        return stats
    try:
        _prepare(db)
        conn = connect(db)
    except sqlite3.Error as exc:
        if not _is_transient(exc):
            raise
        stats["deferred"] = True
        return stats
    try:
        try:
            stats["ingested"] = _ingest_spool(conn, spool_dir(db))
        except sqlite3.Error as exc:
            if not _is_transient(exc):
                raise
            stats["deferred"] = True
            return stats
        for _ in range(max(1, batch)):
            row = conn.execute(
                "SELECT id, kind, payload FROM queue_intents "
                "WHERE applied_at = '' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                break
            outcome = _apply_row(conn, row)
            if outcome == "deferred":
                stats["deferred"] = True
                break
            stats[outcome] += 1
        stats["pending"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM queue_intents WHERE applied_at = ''"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--stop-file", default="")
    args = parser.parse_args(argv)
    stop = Path(args.stop_file) if args.stop_file else None
    try:
        while True:
            stats = drain(args.db)
            if stats["ingested"] or stats["applied"] or stats["refused"] or stats["failed"]:
                print(json.dumps({"intents": stats}), flush=True)
            if args.once or (stop is not None and stop.exists()):
                return 0
            time.sleep(max(0.05, args.interval))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
