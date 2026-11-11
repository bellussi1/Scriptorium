"""Fake worker for the auto_queue supervisor scenarios.

Not a production script. The supervisor runs it through
``AUTO_QUEUE_WORKER_SCRIPT`` and reads ``FAKE_WORKER_MODE``:

- ``sleep``: keep writing a heartbeat until killed;
- ``gate``: write a needs_review block and exit 1;
- ``crash``: exit 1 with an in-progress status;
- ``idle``: exit 0 with no pending books.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    state = Path(os.environ["FAKE_WORKER_STATE_DIR"])
    mode = os.environ.get("FAKE_WORKER_MODE", "sleep")
    status_path = state / "literary_queue.auto.json"

    def write(payload: dict) -> None:
        data = {"heartbeat": _now(), "pid": os.getpid(), **payload}
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    if mode == "gate":
        write(
            {
                "running": False,
                "phase": "blocked",
                "reason": "gate_needs_review",
                "message": "audit failed; human review required",
                "book_id": 1,
                "title": "Fake Gate",
            }
        )
        return 1
    if mode == "crash":
        write(
            {
                "running": True,
                "phase": "starting",
                "reason": "starting",
                "message": "starting queue runner",
            }
        )
        return 1
    if mode == "idle":
        write(
            {
                "running": False,
                "phase": "idle",
                "reason": "no_pending",
                "message": "no pending books",
            }
        )
        return 0
    if mode == "stall":
        write(
            {
                "running": True,
                "phase": "waiting",
                "reason": "active",
                "message": "translation active",
                "book_id": 1,
                "title": "Fake",
            }
        )
        time.sleep(60)
        return 0

    while True:
        write(
            {
                "running": True,
                "phase": "waiting",
                "reason": "active",
                "message": "translation active",
                "book_id": 1,
                "title": "Fake",
            }
        )
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
