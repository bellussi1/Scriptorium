"""Read-only queue status derived from ``literary_queue.db``.

Queue truth (running, book, job, progress, next pending, blockers) is derived
only from the database. The ``supervisor`` block is process metadata read from
``literary_queue.supervisor.json``: it reports whether the supervisor is alive
and the last restart reason, and is never used to decide what is running.
The heartbeat is the newest ``updated_at`` of the active book/job, which the
queue sync refreshes while a translation is running. ``rate`` is chunks per
minute and ``eta`` is seconds.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA = "literary-queue.status"
SCHEMA_VERSION = "1.0"
DEFAULT_STALE_AFTER_S = 120.0
SUPERVISOR_STALE_AFTER_S = 30.0
ACTIVE_STATES = ("preparing", "translating", "reviewing", "validating")
BLOCKER_STATES = ("needs_review", "failed", "paused")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _empty_progress() -> Dict[str, Any]:
    return {"chunks": 0, "total": 0, "percent": 0.0, "rate": None, "eta": None}


def _status(
    snapshot_at: datetime,
    db: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "snapshot_at": _iso(snapshot_at),
        "running": False,
        "book": None,
        "job": None,
        "progress": _empty_progress(),
        "heartbeat_age_s": None,
        "stale": False,
        "next_pending": None,
        "blockers": [],
        "supervisor": None,
        "db": db,
    }


def _supervisor_status(
    db_path: str | Path, snapshot_at: datetime
) -> Optional[Dict[str, Any]]:
    """Read the supervisor process file; never used for queue truth."""
    path = Path(db_path).with_name("literary_queue.supervisor.json")
    if not path.exists():
        return None
    try:
        age = max(0.0, snapshot_at.timestamp() - path.stat().st_mtime)
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    worker = data.get("worker") if isinstance(data.get("worker"), dict) else {}
    restart = data.get("restart") if isinstance(data.get("restart"), dict) else {}
    return {
        "online": age <= SUPERVISOR_STALE_AFTER_S,
        "state": data.get("state"),
        "pid": data.get("pid"),
        "heartbeat_age_s": round(age, 1),
        "worker_running": bool(worker.get("running")),
        "message": data.get("message"),
        "restart": {
            "attempts_last_hour": restart.get("attempts_last_hour"),
            "max_per_hour": restart.get("max_per_hour"),
            "last_reason": restart.get("last_reason"),
            "last_at": restart.get("last_at"),
            "next_attempt_at": restart.get("next_attempt_at"),
            "backoff_s": restart.get("backoff_s"),
        },
    }


def _connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro",
        uri=True,
        timeout=2.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 2000")
    return conn


def _next_pending(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """SELECT id, title, priority
           FROM books
           WHERE status = 'pending'
           ORDER BY priority DESC, series, COALESCE(series_index, 0), id
           LIMIT 1"""
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "title": str(row["title"]),
        "priority": int(row["priority"] or 0),
    }


def _blockers(
    conn: sqlite3.Connection,
    *,
    running: bool,
    next_pending: Optional[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    for row in conn.execute(
        """SELECT id, title, status
           FROM books
           WHERE status IN ('needs_review', 'failed', 'paused')
           ORDER BY status, id"""
    ):
        blockers.append(
            {
                "kind": str(row["status"]),
                "book_id": int(row["id"]),
                "title": str(row["title"]),
            }
        )
    if not running:
        blockers.append(
            {"kind": "runner_stopped"} if next_pending else {"kind": "no_pending"}
        )
    return blockers


def build_queue_status(
    db_path: str | Path = "data/literary_queue.db",
    *,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
) -> Dict[str, Any]:
    """Return a versioned, read-only status snapshot from the queue DB."""
    path = Path(db_path)
    snapshot_at = _now()
    db = {"integrity": "missing", "journal_mode": None}
    status = _status(snapshot_at, db)
    status["supervisor"] = _supervisor_status(path, snapshot_at)

    if not path.exists():
        status["blockers"].append({"kind": "db_missing", "detail": str(path)})
        return status

    try:
        conn = _connect_readonly(path)
    except sqlite3.Error as exc:
        status["db"] = {"integrity": "locked", "journal_mode": None}
        status["blockers"].append({"kind": "db_locked", "detail": str(exc)})
        return status

    try:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
        status["db"] = {"integrity": integrity, "journal_mode": journal_mode}
        if integrity.lower() != "ok":
            status["blockers"].append(
                {"kind": "db_integrity", "detail": integrity}
            )
            return status

        next_pending = _next_pending(conn)
        status["next_pending"] = next_pending

        active = conn.execute(
            """SELECT b.id AS book_id, b.title, b.status AS book_state,
                      b.updated_at AS book_updated_at,
                      j.id AS job_id, j.translation_id,
                      j.current_chapter, j.total_chapters,
                      j.created_at AS job_created_at,
                      j.updated_at AS job_updated_at
               FROM books b
               LEFT JOIN jobs j
                 ON j.id = (SELECT MAX(id) FROM jobs WHERE book_id = b.id)
               WHERE b.status IN ('preparing', 'translating', 'reviewing', 'validating')
               ORDER BY j.updated_at DESC, b.id DESC
               LIMIT 1"""
        ).fetchone()

        if active is not None:
            status["running"] = True
            status["book"] = {
                "id": int(active["book_id"]),
                "title": str(active["title"]),
                "state": str(active["book_state"]),
            }
            if active["job_id"] is not None:
                status["job"] = {
                    "id": int(active["job_id"]),
                    "translation_id": str(active["translation_id"] or ""),
                }
            chunks = int(active["current_chapter"] or 0)
            total = int(active["total_chapters"] or 0)
            percent = round(100.0 * chunks / total, 1) if total else 0.0
            started = _parse(active["job_created_at"])
            elapsed_s = (
                (snapshot_at - started).total_seconds() if started else None
            )
            rate = (
                round(chunks / (elapsed_s / 60.0), 2)
                if elapsed_s and elapsed_s > 0 and chunks > 0
                else None
            )
            if rate and total > chunks:
                eta = int(round((total - chunks) / rate * 60.0))
            elif total and chunks >= total:
                eta = 0
            else:
                eta = None
            status["progress"] = {
                "chunks": chunks,
                "total": total,
                "percent": min(100.0, percent),
                "rate": rate,
                "eta": eta,
            }

            timestamps = [
                stamp
                for stamp in (
                    _parse(active["book_updated_at"]),
                    _parse(active["job_updated_at"]),
                )
                if stamp is not None
            ]
            heartbeat = max(timestamps) if timestamps else None
            if heartbeat is not None:
                age = max(0.0, (snapshot_at - heartbeat).total_seconds())
                status["heartbeat_age_s"] = round(age, 1)
                status["stale"] = age > stale_after_s
            else:
                status["stale"] = True
            if status["stale"]:
                status["blockers"].append(
                    {
                        "kind": "stale_heartbeat",
                        "age_s": status["heartbeat_age_s"],
                        "limit_s": stale_after_s,
                    }
                )

        status["blockers"].extend(
            _blockers(conn, running=status["running"], next_pending=next_pending)
        )
        return status
    except sqlite3.Error as exc:
        status["db"] = {"integrity": f"error: {exc}", "journal_mode": None}
        status["blockers"].append({"kind": "db_error", "detail": str(exc)})
        return status
    finally:
        conn.close()


def format_queue_status(status: Dict[str, Any]) -> str:
    """Render a compact human-readable status for the CLI."""
    book = status.get("book") or {}
    job = status.get("job") or {}
    progress = status.get("progress") or {}
    next_pending = status.get("next_pending") or {}
    blockers = status.get("blockers") or []
    db = status.get("db") or {}
    supervisor = status.get("supervisor") or {}
    if supervisor:
        restart = supervisor.get("restart") or {}
        supervisor_line = (
            f"supervisor: online={'yes' if supervisor.get('online') else 'no'} "
            f"state={supervisor.get('state') or '-'} "
            f"worker={'yes' if supervisor.get('worker_running') else 'no'} "
            f"last_restart={restart.get('last_reason') or '-'} "
            f"({restart.get('attempts_last_hour', 0)}/"
            f"{restart.get('max_per_hour', 0)} in 1h)"
        )
    else:
        supervisor_line = "supervisor: -"
    lines = [
        f"running: {'yes' if status.get('running') else 'no'}",
        (
            f"book: #{book.get('id')} {book.get('title')} ({book.get('state')})"
            if book
            else "book: -"
        ),
        (
            f"job: #{job.get('id')} {job.get('translation_id') or '-'}"
            if job
            else "job: -"
        ),
        (
            "progress: {chunks}/{total} ({percent}%) rate={rate} chunks/min eta={eta}s".format(
                chunks=progress.get("chunks", 0),
                total=progress.get("total", 0),
                percent=progress.get("percent", 0.0),
                rate=progress.get("rate"),
                eta=progress.get("eta"),
            )
        ),
        (
            f"next: #{next_pending.get('id')} {next_pending.get('title')}"
            if next_pending
            else "next: -"
        ),
        f"heartbeat: {status.get('heartbeat_age_s')}s stale={'yes' if status.get('stale') else 'no'}",
        supervisor_line,
        "blockers: " + (", ".join(str(item.get("kind")) for item in blockers) or "none"),
        f"db: {db.get('integrity')}/{db.get('journal_mode')}",
        f"snapshot: {status.get('snapshot_at')}",
    ]
    return "\n".join(lines)
