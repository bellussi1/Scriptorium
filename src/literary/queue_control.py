"""Pause-after-book control for the literary queue runner.

The queue runner is a long-lived CLI process; the web UI must be able to ask
it to stop at the next book boundary without killing a translation mid-chapter.
The request therefore lives in a small JSON file next to the queue database
rather than in the database itself: it is cheap, survives restarts, and never
contends with the runner's SQLite writes.

Semantics: the runner checks the flag at the top of its book loop. If it is
set, the runner records the pause, clears the flag and exits before starting
another book. A request made while a book is translating is honoured when that
book finishes; a request made while the queue is idle means the next run stops
before starting a book.

The file also keeps the last honoured pause so the UI can say "Paused after
<book>" instead of silently losing the request.
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
    }


def _normalize(data: object) -> Dict[str, Any]:
    result = _empty()
    if not isinstance(data, dict):
        return result
    result["pause_after_book"] = bool(data.get("pause_after_book"))
    for key in ("requested_at", "honored_at"):
        value = data.get(key)
        result[key] = str(value) if value else None
    honored = data.get("honored_after")
    if isinstance(honored, dict):
        try:
            book_id = int(honored.get("id"))
        except (TypeError, ValueError):
            book_id = None
        title = honored.get("title")
        if book_id is not None or title:
            result["honored_after"] = {
                "id": book_id,
                "title": str(title or ""),
            }
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
    """Clear a pause request and record which book it stopped after."""
    data = read_control(db_path)
    if not data["pause_after_book"]:
        return data
    data["pause_after_book"] = False
    data["honored_at"] = _now()
    data["honored_after"] = book
    return _write(db_path, data)
