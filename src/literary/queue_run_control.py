"""File-based control channel for the host-side queue runner agent.

The Flask app runs inside a container and cannot spawn host processes. The
Queue UI writes a small run request into the shared ``data`` directory; a
host-side agent watches that file, starts the real ``queue run-all`` process,
and publishes a heartbeat and runner info the app can read back.

The channel is deliberately file-based: it survives container restarts, works
across the Docker bind mount, and never gives the web app the ability to run an
arbitrary command.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# This fork translates exactly one book per runner invocation. There is no
# batch mode: a second book must wait for the first to pass the review gate.
RUN_MODES = {"next"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(db_path: str | Path, suffix: str) -> Path:
    path = Path(db_path)
    return path.with_name(f"{path.stem}.{suffix}")


def request_path(db_path: str | Path) -> Path:
    """File the Queue UI writes and the host agent consumes."""
    return _path(db_path, "run-request.json")


def agent_status_path(db_path: str | Path) -> Path:
    """Host agent heartbeat and last-result file."""
    return _path(db_path, "agent.json")


def runner_info_path(db_path: str | Path) -> Path:
    """Compatibility file also read by ``scripts/pause_queue_agent.py``."""
    return _path(db_path, "runner.json")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    last_error: Optional[PermissionError] = None
    # On Windows a reader (the Flask app polling the heartbeat) can briefly hold
    # the destination open, making os.replace fail with WinError 5. Retry the
    # atomic replace instead of crashing the whole agent.
    for attempt in range(20):
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)
            return payload
        except PermissionError as exc:
            last_error = exc
            time.sleep(min(0.05 * (attempt + 1), 0.5))
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
    raise last_error or PermissionError(f"could not write {path}")


def request_run(
    db_path: str | Path,
    mode: str = "next",
    requested_by: str = "queue-ui",
) -> Dict[str, Any]:
    """Write a run request for the host agent.

    Only ``next`` exists: it runs one pending book and stops at the review
    gate. A second book must never start while the first is still active.
    """
    mode = (mode or "next").strip().lower()
    if mode not in RUN_MODES:
        raise ValueError(f"mode must be one of {sorted(RUN_MODES)}")
    return _write_json(
        request_path(db_path),
        {
            "mode": mode,
            "requested_at": _now(),
            "requested_by": requested_by,
        },
    )


def read_run_request(db_path: str | Path) -> Optional[Dict[str, Any]]:
    payload = _read_json(request_path(db_path))
    return payload or None


def clear_run_request(db_path: str | Path, message: str = "") -> Dict[str, Any]:
    """Consume the request, keeping a copy for the agent's last-result log."""
    path = request_path(db_path)
    payload = _read_json(path)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return payload
    if payload:
        payload["honored_at"] = _now()
        if message:
            payload["message"] = message
    return payload


def write_agent_status(db_path: str | Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a status update and refresh the heartbeat."""
    path = agent_status_path(db_path)
    data = _read_json(path)
    data.update(payload)
    data["pid"] = os.getpid()
    data["heartbeat"] = _now()
    data["heartbeat_epoch"] = time.time()
    return _write_json(path, data)


def read_agent_status(
    db_path: str | Path,
    max_age_s: float = 10.0,
) -> Dict[str, Any]:
    """Return the agent status with an ``online`` flag based on file age.

    File mtime is used instead of the writer's clock: the app runs in a
    container and should not trust a timestamp written by another namespace.
    """
    path = agent_status_path(db_path)
    data = _read_json(path)
    if not data:
        return {"online": False, "heartbeat_age_s": None}
    try:
        age = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        age = None
    data["heartbeat_age_s"] = round(age, 2) if age is not None else None
    data["online"] = age is not None and age <= max_age_s
    return data


def write_runner_info(
    db_path: str | Path,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return _write_json(runner_info_path(db_path), payload)


def read_runner_info(db_path: str | Path) -> Dict[str, Any]:
    return _read_json(runner_info_path(db_path))
