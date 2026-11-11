"""Run the auto_queue supervisor against the fake worker.

Two scenarios, both isolated under ``data/tmp`` with a scratch queue DB:

- ``kill``: the worker is killed; the supervisor detects the death, restarts it
  with backoff and records the reason.
- ``gate``: the worker reports ``gate_needs_review``; the supervisor holds, does
  not restart, and writes ``blocked_gate`` to the supervisor status.

This is a manual scenario runner, not part of pytest. It never touches the live
queue DB or the live supervisor files.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.literary.models import BookRecord  # noqa: E402
from src.literary.queue import QueueStore  # noqa: E402

FAKE = ROOT / "tests" / "standalone" / "fake_auto_queue_worker.py"
SUPERVISOR = ROOT / "scripts" / "auto_queue.py"


def _scratch(name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "data" / "tmp" / f"auto-supervisor-{name}-{stamp}"
    if path.exists():
        shutil.rmtree(path)
    (path / "state").mkdir(parents=True)
    return path


def _db(path: Path, *, gate: bool = False) -> Path:
    db = path / "state" / "queue.db"
    store = QueueStore(str(db))
    if gate:
        book_id = store.add_book(
            BookRecord(
                calibre_id=1,
                title="Fake Gate",
                author="Test",
                languages=["en"],
                epub_path="",
            ),
            priority=1,
        )
    else:
        book_id = 0
    store.close()
    if gate:
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE books SET status = 'needs_review' WHERE id = ?", (book_id,)
            )
            conn.commit()
    return db


def _start(path: Path, db: Path, mode: str) -> subprocess.Popen:
    state = path / "state"
    env = {
        **os.environ,
        "AUTO_QUEUE_WORKER_SCRIPT": str(FAKE),
        "FAKE_WORKER_STATE_DIR": str(state),
        "FAKE_WORKER_MODE": mode,
    }
    return subprocess.Popen(
        [
            sys.executable,
            str(SUPERVISOR),
            "--db",
            str(db),
            "--state-dir",
            str(state),
            "--max-restarts-per-hour",
            "3",
            "--restart-backoff",
            "0.5",
            "--restart-backoff-max",
            "1",
            "--heartbeat-interval",
            "0.2",
            "--heartbeat-timeout",
            "3",
            "--supervise-interval",
            "0.2",
            "--startup-grace",
            "1",
            "--gate-poll-interval",
            "0.5",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _log(path: Path) -> str:
    logs = sorted(
        item
        for item in (path / "state" / "queue-runs").glob("supervisor-*.log")
        if item.name != "supervisor-alerts.log"
    )
    return logs[-1].read_text(encoding="utf-8") if logs else ""


def _wait_for(path: Path, needle: str, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if needle in _log(path):
            return True
        time.sleep(0.1)
    return False


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _worker_pid(path: Path) -> int:
    status_path = path / "state" / "literary_queue.supervisor.json"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            worker = data.get("worker") or {}
            if worker.get("running") and worker.get("pid"):
                return int(worker["pid"])
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError("worker did not start")


def kill_scenario() -> str:
    path = _scratch("kill")
    db = _db(path)
    process = _start(path, db, "sleep")
    try:
        if not _wait_for(path, "starting worker"):
            raise RuntimeError("supervisor did not start the worker")
        pid = _worker_pid(path)
        os.kill(pid, 15)
        if not _wait_for(path, "reason=worker_died"):
            raise RuntimeError("supervisor did not detect the worker death\n" + _log(path))
        if not _wait_for(path, "restarting in"):
            raise RuntimeError("supervisor did not schedule a restart")
        if not _wait_for(path, "attempt 1/3"):
            raise RuntimeError("restart attempt not recorded")
        time.sleep(1.0)
        return _log(path)
    finally:
        _stop(process)


def gate_scenario() -> str:
    path = _scratch("gate")
    db = _db(path, gate=True)
    process = _start(path, db, "gate")
    try:
        if not _wait_for(path, "action=hold"):
            raise RuntimeError("supervisor did not hold on the gate")
        if not _wait_for(path, "gate hold"):
            raise RuntimeError("supervisor did not log the gate hold")
        time.sleep(1.0)
        status = json.loads(
            (path / "state" / "literary_queue.supervisor.json").read_text(
                encoding="utf-8"
            )
        )
        if status.get("state") != "blocked_gate":
            raise RuntimeError(f"unexpected supervisor state: {status.get('state')}")
        log = _log(path)
        if "restarting in" in log:
            raise RuntimeError("supervisor restarted on a gate")
        return log
    finally:
        _stop(process)


def stall_scenario() -> str:
    path = _scratch("stall")
    db = _db(path)
    process = _start(path, db, "stall")
    try:
        if not _wait_for(path, "reason=worker_stalled", timeout=15.0):
            raise RuntimeError(
                "supervisor did not detect the stale heartbeat\n" + _log(path)
            )
        if not _wait_for(path, "restarting in"):
            raise RuntimeError("supervisor did not schedule a stall restart")
        time.sleep(0.8)
        return _log(path)
    finally:
        _stop(process)


def main() -> int:
    print("=== KILL SCENARIO ===")
    print(kill_scenario())
    print("=== STALL SCENARIO ===")
    print(stall_scenario())
    print("=== GATE SCENARIO ===")
    print(gate_scenario())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
