"""JSON API for the persistent literary queue.

The queue database itself is written by ``src/literary/queue.py`` (CLI and the
full-book wrapper). This blueprint reads it for the Queue tab and exposes the
two controlled mutations the UI needs: enqueueing books from the Calibre
inventory and reordering pending entries. It never starts, pauses or validates
a translation job.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request, send_file

from src.literary.models import BookRecord
from src.literary.queue import QueueStore

MAX_BOOKS_PER_ADD = 100


def _db_path() -> Path:
    return Path(os.getenv("LITERARY_QUEUE_DB", "data/literary_queue.db"))


def _inventory_path() -> Path:
    return Path(os.getenv("LITERARY_INVENTORY", "data/calibre/targets.json"))


def _outputs_dir() -> Path:
    return Path(os.getenv("LITERARY_OUTPUT_DIR", "translated_files"))


def _artifact_rank(filename: str, title: str) -> int:
    safe_title = re.sub(r'[<>:"/\\|?*]', "", title).strip().strip(".")
    prefix = f"{safe_title} (pt-BR)"
    if not filename.startswith(prefix) or not filename.endswith(".epub"):
        return 0
    if filename.endswith(".refined.epub"):
        return 4
    if filename.endswith(" - fixed-v2.epub"):
        return 3
    if filename.endswith(" - fixed.epub"):
        return 2
    return 1


def _artifact_for(title: str) -> Optional[Dict[str, Any]]:
    directory = _outputs_dir()
    if not directory.exists():
        return None
    candidates = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        rank = _artifact_rank(path.name, title)
        if rank:
            candidates.append((rank, path))
    if not candidates:
        return None
    rank, path = max(candidates, key=lambda item: (item[0], item[1].stat().st_mtime))
    kind = {4: "refined", 3: "validated", 2: "dropcap_repaired", 1: "draft"}[rank]
    return {
        "filename": path.name,
        "kind": kind,
        "size": path.stat().st_size,
        "path": path,
    }


def _load_inventory() -> List[Dict[str, Any]]:
    path = _inventory_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Calibre inventory not found at {path}; run the inventory command first"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("books") or [])


def _queued_calibre_ids(db_path: Path) -> set[int]:
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        return {
            int(row[0])
            for row in conn.execute("SELECT calibre_id FROM books")
            if row[0] is not None
        }
    except sqlite3.Error:
        return set()
    finally:
        conn.close()


def _container_epub_path(row: Dict[str, Any]) -> str:
    """Prefer the /library container mount, then the original host path."""
    calibre_path = str(row.get("calibre_path") or "").replace("\\", "/").strip("/")
    filename = Path(str(row.get("epub_path") or "").replace("\\", "/")).name
    mapped = f"/library/{calibre_path}/{filename}" if calibre_path and filename else ""
    if mapped and Path(mapped).exists():
        return mapped
    original = str(row.get("epub_path") or "")
    if original and Path(original).exists():
        return original
    return mapped or original


def _is_english(row: Dict[str, Any]) -> bool:
    return any(
        str(language).lower().startswith(("en", "eng"))
        for language in (row.get("languages") or [])
    )


def _book_from_inventory(row: Dict[str, Any]) -> BookRecord:
    allowed = BookRecord.__dataclass_fields__.keys()
    data = {key: value for key, value in row.items() if key in allowed}
    data["epub_path"] = _container_epub_path(row)
    return BookRecord(**data)


def _library_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "calibre_id": row.get("calibre_id"),
        "title": row.get("title") or row.get("epub_title") or "",
        "author": row.get("author") or "",
        "series": row.get("series") or "",
        "series_index": row.get("series_index"),
        "word_count": int(row.get("word_count") or 0),
        "languages": list(row.get("languages") or []),
        "epub_title": row.get("epub_title") or "",
    }


def build_library_inventory(db_path: str | Path) -> Dict[str, Any]:
    """English inventory rows that are not in the queue yet."""
    path = Path(db_path)
    queued = _queued_calibre_ids(path)
    entries = [
        _library_entry(row)
        for row in _load_inventory()
        if row.get("calibre_id") is not None
        and int(row["calibre_id"]) not in queued
        and _is_english(row)
    ]
    entries.sort(
        key=lambda item: (
            str(item.get("author") or "").casefold(),
            str(item.get("series") or "").casefold(),
            item.get("series_index") or 0,
            str(item.get("title") or "").casefold(),
        )
    )
    return {"status": "ok", "count": len(entries), "books": entries}


def build_queue_snapshot(db_path: str | Path) -> Dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {
            "status": "empty",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": {"books": 0, "words": 0, "by_status": {}},
            "books": [],
            "events": [],
        }

    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        books = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    b.id, b.calibre_id, b.title, b.author, b.series,
                    b.series_index, b.status, b.word_count, b.model, b.provider,
                    j.id AS job_id, j.state AS job_state, j.translation_id,
                    j.current_chapter, j.total_chapters, j.error,
                    j.updated_at AS job_updated_at
                FROM books b
                LEFT JOIN jobs j
                    ON j.id = (SELECT MAX(id) FROM jobs WHERE book_id = b.id)
                ORDER BY
                    CASE
                        WHEN COALESCE(j.state, b.status) IN
                             ('translating', 'preparing', 'reviewing', 'validating')
                        THEN 0 ELSE 1
                    END,
                    b.priority DESC, b.series, COALESCE(b.series_index, 0), b.id
                """
            )
        ]
        events = [
            dict(row)
            for row in conn.execute(
                "SELECT level, message, created_at FROM events "
                "ORDER BY id DESC LIMIT 10"
            )
        ]
    finally:
        conn.close()

    by_status: Dict[str, int] = {}
    for book in books:
        artifact = _artifact_for(str(book.get("title") or ""))
        if artifact:
            book["artifact"] = {
                "filename": artifact["filename"],
                "kind": artifact["kind"],
                "size": artifact["size"],
                "download_url": f"/api/literary/queue/books/{book['id']}/download",
            }
        state = book.get("job_state") or book.get("status") or "pending"
        by_status[state] = by_status.get(state, 0) + 1

    return {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "books": len(books),
            "words": sum(int(book.get("word_count") or 0) for book in books),
            "by_status": by_status,
        },
        "books": books,
        "events": events,
    }


def _json_error(message: str, status: int = 400):
    return jsonify({"status": "error", "error": message}), status


def _parse_calibre_ids(payload: Dict[str, Any]) -> Optional[List[int]]:
    raw = payload.get("calibre_ids")
    if not isinstance(raw, list) or not raw:
        return None
    ids: List[int] = []
    for value in raw:
        try:
            calibre_id = int(value)
        except (TypeError, ValueError):
            return None
        if calibre_id <= 0:
            return None
        if calibre_id not in ids:
            ids.append(calibre_id)
    if len(ids) > MAX_BOOKS_PER_ADD:
        return None
    return ids


def create_literary_queue_blueprint() -> Blueprint:
    bp = Blueprint("literary_queue", __name__)

    @bp.route("/api/literary/queue", methods=["GET"])
    def get_literary_queue():
        try:
            return jsonify(build_queue_snapshot(_db_path()))
        except Exception as exc:  # pragma: no cover - defensive boundary
            return _json_error(str(exc), 500)

    @bp.route("/api/literary/library", methods=["GET"])
    def get_literary_library():
        try:
            return jsonify(build_library_inventory(_db_path()))
        except FileNotFoundError as exc:
            return _json_error(str(exc), 503)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return _json_error(str(exc), 500)

    @bp.route("/api/literary/queue/books", methods=["POST"])
    def add_literary_queue_books():
        payload = request.get_json(silent=True) or {}
        calibre_ids = _parse_calibre_ids(payload)
        if calibre_ids is None:
            return _json_error(
                "calibre_ids must be a non-empty list of positive integers "
                f"(maximum {MAX_BOOKS_PER_ADD})"
            )

        try:
            inventory = {int(row["calibre_id"]): row for row in _load_inventory()
                         if row.get("calibre_id") is not None}
        except FileNotFoundError as exc:
            return _json_error(str(exc), 503)

        db_path = _db_path()
        queued = _queued_calibre_ids(db_path)
        not_found = [calibre_id for calibre_id in calibre_ids if calibre_id not in inventory]
        ineligible = [
            calibre_id
            for calibre_id in calibre_ids
            if calibre_id in inventory and not _is_english(inventory[calibre_id])
        ]
        if ineligible:
            return _json_error(
                "only English source books can be enqueued: "
                + ", ".join(str(calibre_id) for calibre_id in ineligible)
            )
        duplicates = [calibre_id for calibre_id in calibre_ids if calibre_id in queued]
        selected = [
            inventory[calibre_id]
            for calibre_id in calibre_ids
            if calibre_id in inventory and calibre_id not in queued
        ]

        added: List[int] = []
        store: Optional[QueueStore] = None
        try:
            if selected:
                store = QueueStore(str(db_path))
                for row in selected:
                    book_id = store.add_book(
                        _book_from_inventory(row),
                        target_language=str(payload.get("target_language") or "pt-BR"),
                        priority=store.next_pending_priority(),
                        model=str(payload.get("model") or ""),
                        provider=str(payload.get("provider") or ""),
                    )
                    added.append(book_id)
            snapshot = build_queue_snapshot(db_path)
        finally:
            if store is not None:
                store.close()

        snapshot["added"] = added
        snapshot["duplicates"] = duplicates
        snapshot["not_found"] = not_found
        return jsonify(snapshot), (201 if added else 200)

    @bp.route("/api/literary/queue/books/<int:book_id>", methods=["PATCH"])
    def update_literary_queue_book(book_id: int):
        payload = request.get_json(silent=True) or {}
        model = str(payload.get("model") or "").strip()
        provider = str(payload.get("provider") or "").strip()
        if not model:
            return _json_error("model is required")

        store = QueueStore(str(_db_path()))
        try:
            if not store.update_book_model(book_id, model, provider):
                return _json_error("book not found", 404)
            snapshot = build_queue_snapshot(_db_path())
        except ValueError as exc:
            return _json_error(str(exc), 409)
        finally:
            store.close()

        snapshot["updated"] = {
            "book_id": book_id,
            "model": model,
            "provider": provider,
        }
        return jsonify(snapshot)

    @bp.route("/api/literary/queue/books/<int:book_id>/download", methods=["GET"])
    def download_literary_queue_book(book_id: int):
        book = QueueStore.get_book_readonly(str(_db_path()), book_id)
        if book is None:
            return _json_error("book not found", 404)
        artifact = _artifact_for(book.title)
        if artifact is None:
            return _json_error("translated EPUB not found", 404)
        return send_file(
            str(artifact["path"]),
            as_attachment=True,
            download_name=artifact["filename"],
            mimetype="application/epub+zip",
        )

    @bp.route("/api/literary/queue/books/<int:book_id>/move", methods=["POST"])
    def move_literary_queue_book(book_id: int):
        payload = request.get_json(silent=True) or {}
        direction = str(payload.get("direction") or "").strip().lower()
        if direction not in {"up", "down"}:
            return _json_error("direction must be 'up' or 'down'")

        store = QueueStore(str(_db_path()))
        try:
            book = store.get_book(book_id)
            if book is None:
                return _json_error("book not found", 404)
            if book.status != "pending":
                return _json_error("only pending books can be reordered", 409)
            if not store.move_book(book_id, direction):
                return _json_error("book is already at the edge of the queue", 409)
            snapshot = build_queue_snapshot(_db_path())
        except ValueError as exc:
            return _json_error(str(exc), 400)
        finally:
            store.close()

        snapshot["moved"] = {"book_id": book_id, "direction": direction}
        return jsonify(snapshot)

    return bp
