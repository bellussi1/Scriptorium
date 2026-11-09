"""Pause controls for the literary queue runner.

Two requests live here, both in a small JSON file next to the queue database
rather than in SQLite: it is cheap, survives restarts, and never contends with
the runner's database writes.

- ``pause_after_book`` stops the runner at the next book boundary.
- ``pause_now`` stops the book currently being translated at a safe checkpoint
  and stops the runner, so it cannot start the next book.

The file also keeps the last honoured request so the UI can say what happened
instead of silently losing it.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def control_path(db_path: str | Path) -> Path:
    """Return the control file that belongs to a queue database."""
    path = Path(db_path)
    return path.with_name(f"{path.stem}.control.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> Dict[str, Any]:
    return {
        "pause_after_book": False,
        "requested_at": None,
        "honored_at": None,
        "honored_after": None,
        "pause_now": False,
        "pause_now_requested_at": None,
        "pause_now_honored_at": None,
        "pause_now_honored_after": None,
    }


def _book(value: object) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    try:
        book_id = int(value.get("id"))
    except (TypeError, ValueError):
        book_id = None
    title = value.get("title")
    if book_id is None and not title:
        return None
    return {"id": book_id, "title": str(title or "")}


def _normalize(data: object) -> Dict[str, Any]:
    result = _empty()
    if not isinstance(data, dict):
        return result
    result["pause_after_book"] = bool(data.get("pause_after_book"))
    for key in ("requested_at", "honored_at", "pause_now_requested_at", "pause_now_honored_at"):
        value = data.get(key)
        result[key] = str(value) if value else None
    result["honored_after"] = _book(data.get("honored_after"))
    result["pause_now"] = bool(data.get("pause_now"))
    result["pause_now_honored_after"] = _book(data.get("pause_now_honored_after"))
    return result


def read_control(db_path: str | Path) -> Dict[str, Any]:
    """Read the current control state; missing or corrupt files read as idle."""
    path = control_path(db_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    return _normalize(payload)


def _write(db_path: str | Path, data: Dict[str, Any]) -> Dict[str, Any]:
    path = control_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return data


def set_pause(db_path: str | Path, pause: bool) -> Dict[str, Any]:
    """Request or cancel a pause after the current book."""
    data = read_control(db_path)
    if pause:
        data["pause_after_book"] = True
        data["requested_at"] = _now()
        data["honored_at"] = None
        data["honored_after"] = None
    else:
        data["pause_after_book"] = False
        data["requested_at"] = None
    return _write(db_path, data)


def pause_requested(db_path: str | Path) -> bool:
    return bool(read_control(db_path)["pause_after_book"])


def honor_pause(
    db_path: str | Path,
    book: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clear a pause-after-book request and record which book it stopped after."""
    data = read_control(db_path)
    if not data["pause_after_book"]:
        return data
    data["pause_after_book"] = False
    data["honored_at"] = _now()
    data["honored_after"] = book
    return _write(db_path, data)


def set_pause_now(db_path: str | Path, pause: bool) -> Dict[str, Any]:
    """Request or cancel an immediate pause of the book being translated."""
    data = read_control(db_path)
    if pause:
        data["pause_now"] = True
        data["pause_now_requested_at"] = _now()
        data["pause_now_honored_at"] = None
        data["pause_now_honored_after"] = None
    else:
        data["pause_now"] = False
        data["pause_now_requested_at"] = None
    return _write(db_path, data)


def pause_now_requested(db_path: str | Path) -> bool:
    return bool(read_control(db_path)["pause_now"])


def honor_pause_now(
    db_path: str | Path,
    book: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clear an immediate pause request and record which book it stopped."""
    data = read_control(db_path)
    if not data["pause_now"]:
        return data
    data["pause_now"] = False
    data["pause_now_honored_at"] = _now()
    data["pause_now_honored_after"] = book
    return _write(db_path, data)
