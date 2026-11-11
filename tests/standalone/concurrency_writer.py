"""Independent writer used by the concurrency baseline.

It simulates the queue runner's periodic writes while a book is translating:
short ``BEGIN IMMEDIATE`` transactions against the queue DB, updating the
active job and occasionally appending an event. In ``hold`` mode it keeps a
write transaction open for a fixed number of seconds, which is how the
baseline measures the 30 s SQLite busy timeout.

The script has no project imports on purpose: it must run both on the Windows
host and inside the app container (through the /app/data bind mount).

Examples::

    python tests/standalone/concurrency_writer.py \
        --db data/tmp/concurrency-baseline/queue.db --seconds 30 --interval 0.01

    python tests/standalone/concurrency_writer.py \
        --db data/tmp/concurrency-baseline/queue.db --mode hold --hold-seconds 35
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{_now()}] {message}\n")
        handle.flush()


def _pick_job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
    if job_id:
        row = conn.execute(
            "SELECT id, book_id, current_chapter, total_chapters, state "
            "FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, book_id, current_chapter, total_chapters, state "
            "FROM jobs WHERE state = 'translating' ORDER BY id LIMIT 1"
        ).fetchone()
    if row is None:
        raise SystemExit("no translating job found")
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--job-id", type=int, default=0)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=0.01)
    parser.add_argument("--mode", choices=["short", "hold"], default="short")
    parser.add_argument("--hold-seconds", type=float, default=35.0)
    parser.add_argument("--stop-file", default="")
    parser.add_argument("--log", default="")
    args = parser.parse_args()

    db = Path(args.db)
    log_path = Path(args.log) if args.log else db.with_name("writer.log")
    if not db.exists():
        raise SystemExit(f"database not found: {db}")

    conn = sqlite3.connect(str(db), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        conn.execute("PRAGMA journal_mode = DELETE")
    except sqlite3.OperationalError as exc:
        _log(log_path, f"writer_journal_pragma_failed {exc}")

    try:
        job = _pick_job(conn, args.job_id)
        job_id = int(job["id"])
        book_id = int(job["book_id"])
        current = int(job["current_chapter"] or 0)
        total = int(job["total_chapters"] or 0)
        _log(
            log_path,
            f"writer_start mode={args.mode} job={job_id} book={book_id} "
            f"state={job['state']} progress={current}/{total} pid={os.getpid()}",
        )

        if args.mode == "hold":
            deadline = time.time() + 10
            while True:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    break
                except sqlite3.OperationalError as exc:
                    _log(log_path, f"hold_begin_retry {exc}")
                    if time.time() > deadline:
                        raise
                    time.sleep(0.2)
            conn.execute(
                "UPDATE jobs SET current_chapter = ?, updated_at = ? WHERE id = ?",
                (min(total, current + 1) if total else current + 1, _now(), job_id),
            )
            _log(log_path, f"hold_start job={job_id} seconds={args.hold_seconds}")
            time.sleep(max(0.0, args.hold_seconds))
            conn.execute("COMMIT")
            _log(log_path, "hold_end")
            print(json.dumps({"mode": "hold", "job_id": job_id, "held_s": args.hold_seconds}))
            return 0

        deadline = time.time() + max(0.0, args.seconds)
        stop_path = Path(args.stop_file) if args.stop_file else None
        iterations = 0
        lock_errors = 0
        io_errors = 0
        other_errors = 0
        while time.time() < deadline:
            if stop_path is not None and stop_path.exists():
                _log(log_path, "writer_stop requested")
                break
            try:
                conn.execute("BEGIN IMMEDIATE")
                if stop_path is not None and stop_path.exists():
                    conn.execute("ROLLBACK")
                    _log(log_path, "writer_stop requested after lock")
                    break
                iterations += 1
                progress = current + iterations
                if total:
                    progress = min(total, progress)
                conn.execute(
                    "UPDATE jobs SET current_chapter = ?, updated_at = ? WHERE id = ?",
                    (progress, _now(), job_id),
                )
                if iterations % 20 == 0:
                    conn.execute(
                        "INSERT INTO events (book_id, job_id, level, message, created_at) "
                        "VALUES (?, ?, 'info', ?, ?)",
                        (book_id, job_id, f"translator progress {progress}/{total}", _now()),
                    )
                conn.execute("COMMIT")
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "locked" in message:
                    lock_errors += 1
                    kind = "locked"
                elif "disk i/o" in message:
                    io_errors += 1
                    kind = "io"
                else:
                    other_errors += 1
                    kind = "other"
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                _log(log_path, f"writer_error kind={kind} {exc}")
            time.sleep(max(0.0, args.interval))

        _log(
            log_path,
            f"writer_end iterations={iterations} lock_errors={lock_errors} "
            f"io_errors={io_errors} other_errors={other_errors}",
        )
        print(
            json.dumps(
                {
                    "mode": "short",
                    "job_id": job_id,
                    "iterations": iterations,
                    "lock_errors": lock_errors,
                    "io_errors": io_errors,
                    "other_errors": other_errors,
                }
            )
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
