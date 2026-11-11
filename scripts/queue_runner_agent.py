"""Host-side supervisor for the Queue UI's Run buttons.

The Flask app runs inside a container and cannot start host processes. This
agent watches ``data/literary_queue.run-request.json``, starts the real
``queue run-all`` command on the host, and publishes a heartbeat the app reads
through the shared ``data`` mount.

Only one mode exists:

- ``next``: one pending book, stop at the review gate, export Kindle.

There is no batch mode. The next book must wait until the first is reviewed and
the queue is advanced.

The agent never starts a second runner while one is alive. It is intentionally
a standalone host script: run it with ``python scripts/queue_runner_agent.py``
or via ``start-queue-agent.bat``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.literary.queue import QueueStore  # noqa: E402
from src.literary.queue_run_control import (  # noqa: E402
    clear_run_request,
    read_agent_status,
    read_run_request,
    read_runner_info,
    write_agent_status,
    write_runner_info,
)
from src.literary.queue_intents import drain as drain_intents  # noqa: E402
from src.literary.queue_runner import active_direct_translation, output_name  # noqa: E402

DEFAULT_DB = ROOT / "data" / "literary_queue.db"
LOG_DIR = ROOT / "data" / "queue-runs"
DEFAULT_INTERVAL = 2.0
# Queue changes from the UI are applied on this cadence; heartbeats keep
# DEFAULT_INTERVAL.
INTENT_INTERVAL = 0.5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _runner_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return str(pid) in (completed.stdout or "")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pending_book(db: Path):
    store = QueueStore(str(db))
    try:
        return store.next_pending()
    finally:
        store.close()


def _add_event(db: Path, message: str, *, book_id: int | None = None, level: str = "info") -> None:
    store = QueueStore(str(db))
    try:
        store.add_event(message, book_id=book_id, level=level)
    finally:
        store.close()


def _command(db: Path, mode: str) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "src.literary.cli",
        "queue",
        "run-all",
        "--db",
        str(db),
        "--parallel",
        "1",
        "--refine-limit",
        "0",
        "--export-kindle",
        "--outputs",
        "translated_files",
        "--kindle-out",
        "translated_files/kindle",
    ]
    # Always exactly one book, always stop at the review gate. The old batch
    # mode was removed so a second book cannot start automatically.
    command.extend(["--max-books", "1", "--stop-on-review"])
    return command


def _publish(db: Path, **payload) -> None:
    write_agent_status(db, payload)


def _apply_intents(db: Path) -> None:
    """Apply queued UI changes: the agent is the only writer of the queue DB."""
    try:
        stats = drain_intents(db)
    except Exception as exc:  # keep the agent alive; the next pass retries
        print(f"run: queue intents not applied: {exc}", flush=True)
        return
    if stats["ingested"] or stats["applied"] or stats["refused"] or stats["failed"]:
        print(f"run: queue intents {json.dumps(stats)}", flush=True)


def _process_request(db: Path, request: dict, *, dry_run: bool) -> int:
    mode = str(request.get("mode") or "next").strip().lower()
    if mode != "next":
        clear_run_request(db, "one book per run")
        _publish(
            db,
            running=False,
            message="one book per run",
            last_result="one book per run",
            last_request=request,
        )
        print("run: one book per run; batch requests are refused", flush=True)
        return 0
    pending = _pending_book(db)
    if pending is None:
        clear_run_request(db, "no pending books")
        _publish(
            db,
            running=False,
            message="no pending books",
            last_result="no pending books",
            last_request=request,
        )
        print("run: no pending books", flush=True)
        return 0

    store = QueueStore(str(db))
    try:
        latest = store.latest_job(pending.id)
        exclude = str((latest or {}).get("translation_id") or "")
    finally:
        store.close()
    active = active_direct_translation(
        db.with_name("jobs.mirror.db"),
        exclude_translation_id=exclude,
    )
    if active:
        clear_run_request(db, "another translation active")
        _publish(
            db,
            running=False,
            message="another translation active",
            last_result="another translation active",
            last_request=request,
        )
        print("run: another translation is active; one book at a time", flush=True)
        return 0

    current = read_runner_info(db)
    current_pid = int(current.get("runner_pid") or 0)
    if current.get("running") and _runner_alive(current_pid):
        clear_run_request(db, "runner already active")
        _publish(
            db,
            running=True,
            runner_pid=current_pid,
            message="runner already active",
            last_result="runner already active",
            last_request=request,
        )
        print(f"run: runner {current_pid} already active", flush=True)
        return 0

    clear_run_request(db, "starting")
    _add_event(
        db,
        f"queue runner starting from Queue UI ({mode}): {pending.title}",
        book_id=pending.id,
    )
    command = _command(db, mode)
    started_at = _now()
    print("run:", " ".join(command), flush=True)

    if dry_run:
        write_runner_info(db, {
            "runner_pid": 0,
            "running": False,
            "dry_run": True,
            "book_id": pending.id,
            "title": pending.title,
            "output_name": output_name(pending),
            "mode": mode,
            "command": command,
            "started_at": started_at,
        })
        _publish(
            db,
            running=False,
            message="dry run",
            last_result="dry run",
            last_request=request,
            command=command,
        )
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOG_DIR / f"agent-runner-{stamp}.log"
    with log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

    runner_info = {
        "runner_pid": process.pid,
        "running": True,
        "book_id": pending.id,
        "title": pending.title,
        "output_name": output_name(pending),
        "mode": mode,
        "command": command,
        "started_at": started_at,
        "log_path": str(log_path),
    }
    write_runner_info(db, runner_info)
    _publish(
        db,
        running=True,
        runner_pid=process.pid,
        mode=mode,
        book_id=pending.id,
        title=pending.title,
        log_path=str(log_path),
        message="runner started",
        last_request=request,
        command=command,
    )
    print(f"run: started PID {process.pid}; log={log_path}", flush=True)

    while process.poll() is None:
        _publish(
            db,
            running=True,
            runner_pid=process.pid,
            mode=mode,
            book_id=pending.id,
            title=pending.title,
            log_path=str(log_path),
            message="runner active",
            last_request=request,
            command=command,
        )
        time.sleep(DEFAULT_INTERVAL)

    exit_code = int(process.returncode or 0)
    finished_at = _now()
    write_runner_info(db, {
        **runner_info,
        "running": False,
        "finished_at": finished_at,
        "exit_code": exit_code,
    })
    _publish(
        db,
        running=False,
        timestamp=finished_at,
        last_exit_code=exit_code,
        message="runner finished",
        last_result={"exit_code": exit_code, "book_id": pending.id, "title": pending.title},
        last_request=request,
    )
    _add_event(
        db,
        f"queue runner finished from Queue UI (exit {exit_code})",
        book_id=pending.id,
        level="info" if exit_code == 0 else "warning",
    )
    print(f"run: finished with exit {exit_code}", flush=True)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true", help="check one request and exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="record the command and clear the request without starting the runner",
    )
    args = parser.parse_args()
    db = Path(args.db)
    if not db.exists():
        print(f"run: queue database not found: {db}", flush=True)
        return 1

    existing = read_agent_status(db)
    existing_pid = int(existing.get("pid") or 0)
    if existing_pid and existing_pid != os.getpid() and _runner_alive(existing_pid):
        print(f"run: another agent is already active (PID {existing_pid})", flush=True)
        return 1

    _publish(db, running=False, started_at=_now(), message="agent online")
    print(f"run: agent online; watching {db}", flush=True)
    try:
        last_heartbeat = 0.0
        while True:
            _apply_intents(db)
            request = read_run_request(db)
            if request:
                code = _process_request(db, request, dry_run=args.dry_run)
                if args.once:
                    return code
            elif time.monotonic() - last_heartbeat >= args.interval:
                _publish(db, running=False, message="agent online")
                last_heartbeat = time.monotonic()
                if args.once:
                    return 0
            time.sleep(max(0.2, min(args.interval, INTENT_INTERVAL)))
    except KeyboardInterrupt:
        _publish(db, running=False, message="agent stopped", stopped_at=_now())
        print("run: agent stopped", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
