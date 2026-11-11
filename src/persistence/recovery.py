"""Recover the live jobs database from the latest good snapshot.

The live DB is on a Docker volume, so a corrupt file is not a filesystem
problem the host can inspect. At app startup we check it once; if it is
corrupt, the current file is preserved as ``jobs-corrupt-<timestamp>.db`` and
the newest snapshot that passes ``integrity_check`` is promoted into place.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _integrity(path: Path) -> str:
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return str(row[0] if row else "unknown")
        finally:
            conn.close()
    except Exception as exc:
        return f"error: {exc}"


def recover_live_db_if_needed(
    live_path: Optional[str] = None,
    backup_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Check the live DB and promote the newest healthy snapshot if needed.

    Returns a small status dict for the startup log. A missing live DB is not
    an error: the app creates it on first start. If no healthy snapshot exists,
    the corrupt file is left in place and the normal startup integrity check
    fails loudly.
    """
    live = Path(live_path or os.getenv("JOBS_DB_PATH", "data/jobs.db"))
    backups = Path(backup_dir or os.getenv("JOBS_BACKUP_DIR", "data/backups"))
    if not live.exists():
        return {"status": "missing", "path": str(live)}

    check = _integrity(live)
    if check.lower() == "ok":
        return {"status": "ok", "path": str(live), "integrity": check}

    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    corrupt_copy = backups / f"jobs-corrupt-{stamp}.db"
    try:
        shutil.copy2(live, corrupt_copy)
    except OSError:
        corrupt_copy = None

    candidates = sorted(
        backups.glob("jobs-*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        name = candidate.name
        if name.startswith(("jobs-corrupt-", "jobs-old-", "jobs-pre-volume-")):
            continue
        if _integrity(candidate).lower() != "ok":
            continue
        temporary = live.with_name(live.name + ".restore.tmp")
        try:
            shutil.copy2(candidate, temporary)
            os.replace(temporary, live)
        except OSError as exc:
            return {
                "status": "corrupt",
                "path": str(live),
                "error": str(exc),
                "corrupt_copy": str(corrupt_copy) if corrupt_copy else None,
            }
        restored = _integrity(live)
        return {
            "status": "restored" if restored.lower() == "ok" else "restore_failed",
            "path": str(live),
            "snapshot": str(candidate),
            "integrity": restored,
            "corrupt_copy": str(corrupt_copy) if corrupt_copy else None,
        }

    return {
        "status": "corrupt",
        "path": str(live),
        "error": check,
        "corrupt_copy": str(corrupt_copy) if corrupt_copy else None,
    }
