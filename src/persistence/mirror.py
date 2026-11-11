"""Consistent read-only snapshots of the live jobs database.

The live ``jobs.db`` lives on a Docker named volume and has exactly one writer:
the app container. The host queue runner must never open that file. Instead,
this module exports a full SQLite backup to ``jobs.mirror.db`` on the bind
mount every ``JOBS_MIRROR_INTERVAL`` seconds; the host reads the mirror with a
plain read-only connection.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LIVE_DB = os.getenv("JOBS_DB_PATH", "data/jobs.db")
MIRROR_DB = os.getenv("JOBS_MIRROR_PATH", "data/jobs.mirror.db")
INTERVAL = max(5, int(os.getenv("JOBS_MIRROR_INTERVAL", "30")))


def export_mirror(
    live_path: Optional[str] = None,
    mirror_path: Optional[str] = None,
) -> bool:
    """Copy the live database to the mirror atomically and consistently.

    Uses the SQLite backup API, so a write in flight cannot produce a torn
    copy. The mirror is replaced with ``os.replace`` only after a quick_check.
    """
    live = Path(live_path or LIVE_DB)
    mirror = Path(mirror_path or MIRROR_DB)
    if not live.exists():
        return False

    mirror.parent.mkdir(parents=True, exist_ok=True)
    tmp = mirror.with_name(mirror.name + ".tmp")
    src = sqlite3.connect(f"file:{live.as_posix()}?mode=ro", uri=True, timeout=10)
    dst = sqlite3.connect(str(tmp))
    try:
        src.backup(dst)
        dst.commit()
        row = dst.execute("PRAGMA quick_check").fetchone()
        integrity = str(row[0] if row else "unknown")
        if integrity.lower() != "ok":
            raise RuntimeError(f"mirror integrity check failed: {integrity}")
    finally:
        dst.close()
        src.close()

    os.replace(tmp, mirror)

    sidecar = mirror.with_suffix(".json")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(live),
        "mirror": str(mirror),
        "size": mirror.stat().st_size,
        "integrity": integrity,
    }
    sidecar_tmp = sidecar.with_name(sidecar.name + ".tmp")
    sidecar_tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(sidecar_tmp, sidecar)
    return True


def _loop() -> None:
    while True:
        try:
            export_mirror()
        except Exception as exc:  # never kill the web app over a mirror failure
            logger.warning("jobs mirror export failed: %s", exc)
        time.sleep(INTERVAL)


def start_mirror_exporter() -> Optional[threading.Thread]:
    """Export once immediately, then keep the mirror fresh in a daemon thread."""
    if os.getenv("JOBS_MIRROR_ENABLED", "1").strip().lower() in {"0", "false", "no"}:
        return None
    try:
        export_mirror()
    except Exception as exc:
        logger.warning("initial jobs mirror export failed: %s", exc)
    thread = threading.Thread(target=_loop, name="jobs-mirror", daemon=True)
    thread.start()
    return thread
