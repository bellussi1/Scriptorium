"""Host-side bridge for the queue's "Pause now" button.

New queue runners honour ``pause_now`` themselves. A runner started before that
code existed cannot, so this small agent watches the same control file and, when
the request appears:

1. stops the ``run-all`` wrapper so it cannot start the next book;
2. stops the container-side ``translate.py`` with SIGTERM (the per-chunk
   checkpoint is already on disk);
3. marks the book and its latest job as ``paused``;
4. records the honoured request in the control file and exits.

It is intentionally a standalone host script: the Flask app runs in a
container and cannot see host PIDs or run Docker. Do not run it while a runner
that already supports ``pause_now`` is active; the runner will handle the
request first.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.literary.queue import QueueStore  # noqa: E402
from src.literary.queue_control import (  # noqa: E402
    honor_pause_now,
    pause_now_requested,
    set_pause,
)

DEFAULT_DB = ROOT / "data" / "literary_queue.db"
RUNNER_INFO = ROOT / "data" / "literary_queue.runner.json"
COMPOSE = ["docker", "compose", "-f", "docker-compose.dev.yml"]


def _runner_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return str(pid) in (completed.stdout or "")


def _signal_translation(output_name: str, sig: str) -> None:
    subprocess.run(
        COMPOSE + [
            "exec", "-T", "app", "python", "-m", "src.literary.kill_translation",
            output_name, "--signal", sig,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _kill_runner(pid: int) -> None:
    if not _runner_alive(pid):
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _kill_translation(output_name: str) -> None:
    _signal_translation(output_name, "TERM")
    time.sleep(10)
    _signal_translation(output_name, "KILL")


def _latest_job_id(db: Path, book_id: int) -> int | None:
    conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT id FROM jobs WHERE book_id = ? ORDER BY id DESC LIMIT 1",
            (book_id,),
        ).fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def _mark_paused(db: Path, book_id: int, title: str) -> None:
    store = QueueStore(str(db))
    try:
        job_id = _latest_job_id(db, book_id)
        if job_id is not None:
            try:
                store.set_job_state(job_id, "paused", "paused by user from the queue UI")
            except ValueError:
                pass
        try:
            store.set_book_state(book_id, "paused", "paused by user from the queue UI")
        except ValueError:
            pass
        store.add_event(
            "queue runner paused by user",
            book_id=book_id,
            job_id=job_id,
            level="warning",
        )
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--runner-info", default=str(RUNNER_INFO))
    parser.add_argument("--once", action="store_true", help="check once and exit")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be stopped without killing anything",
    )
    args = parser.parse_args()
    db = Path(args.db)
    runner_info_path = Path(args.runner_info)

    while True:
        if not pause_now_requested(db):
            if args.once:
                return 0
            try:
                current = json.loads(runner_info_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            current_pid = int(current.get("runner_pid") or 0)
            if current_pid and not _runner_alive(current_pid):
                print("pause-now: runner exited; stopping agent", flush=True)
                return 0
            time.sleep(args.interval)
            continue

        try:
            info = json.loads(runner_info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        book_id = info.get("book_id")
        title = str(info.get("title") or "")
        runner_pid = int(info.get("runner_pid") or 0)
        output_name = str(info.get("output_name") or "")
        if not book_id:
            print("pause-now: no runner info; clearing the request", flush=True)
            honor_pause_now(db, None)
            return 1

        print(
            f"pause-now: stopping {title!r} (book {book_id}, runner {runner_pid})",
            flush=True,
        )
        if args.dry_run:
            print(
                f"pause-now: dry run; runner alive={_runner_alive(runner_pid)} "
                f"output={output_name!r}",
                flush=True,
            )
            return 0

        # Stop the wrapper first so it cannot overwrite the paused state with a
        # failed/no-output transition while the container process dies.
        _kill_runner(runner_pid)
        _kill_translation(output_name)
        time.sleep(1)
        _mark_paused(db, int(book_id), title)
        honor_pause_now(db, {"id": int(book_id), "title": title})
        set_pause(db, False)
        print("pause-now: paused", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
