"""Tests for the read-only queue status snapshot."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.literary.models import BookRecord
from src.literary.queue import QueueStore
from src.literary.status import build_queue_status

ROOT = Path(__file__).resolve().parents[2]


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _add_book(store: QueueStore, title: str, *, priority: int = 0) -> int:
    return store.add_book(
        BookRecord(
            calibre_id=abs(hash(title)) % 100000,
            title=title,
            author="Test Author",
            series="Test Series",
            series_index=1.0,
            languages=["en"],
            epub_path="",
        ),
        priority=priority,
    )


def _active_book(
    db: Path,
    *,
    title: str = "Running Book",
    chunks: int = 5,
    total: int = 10,
    age_seconds: int = 0,
    created_seconds: int = 300,
) -> tuple[int, int]:
    store = QueueStore(str(db))
    try:
        book_id = _add_book(store, title, priority=100)
        job_id = store.create_job(book_id, total_chapters=total)
        store.attach_translation_id(job_id, "cli_running")
    finally:
        store.close()

    now = datetime.now(timezone.utc)
    updated = _iso(now - timedelta(seconds=age_seconds))
    created = _iso(now - timedelta(seconds=created_seconds))
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE books SET status = 'translating', updated_at = ? WHERE id = ?",
            (updated, book_id),
        )
        conn.execute(
            """UPDATE jobs
               SET state = 'translating', current_chapter = ?, total_chapters = ?,
                   created_at = ?, updated_at = ?
               WHERE id = ?""",
            (chunks, total, created, updated, job_id),
        )
        conn.commit()
    return book_id, job_id


def test_running_book_has_book_job_and_progress(tmp_path: Path):
    db = tmp_path / "queue.db"
    book_id, job_id = _active_book(db)
    store = QueueStore(str(db))
    try:
        next_id = _add_book(store, "Next Book", priority=10)
    finally:
        store.close()

    status = build_queue_status(db)

    assert status["schema"] == "literary-queue.status"
    assert status["schema_version"] == "1.0"
    assert status["running"] is True
    assert status["book"] == {
        "id": book_id,
        "title": "Running Book",
        "state": "translating",
    }
    assert status["job"] == {"id": job_id, "translation_id": "cli_running"}
    assert status["progress"]["chunks"] == 5
    assert status["progress"]["total"] == 10
    assert status["progress"]["percent"] == 50.0
    assert status["progress"]["rate"] > 0
    assert status["progress"]["eta"] > 0
    assert status["heartbeat_age_s"] < 10
    assert status["stale"] is False
    assert status["next_pending"]["id"] == next_id
    assert status["db"]["integrity"] == "ok"
    assert status["db"]["journal_mode"] == "delete"


def test_runner_stopped_reports_next_pending_not_running(tmp_path: Path):
    db = tmp_path / "queue.db"
    store = QueueStore(str(db))
    try:
        book_id = _add_book(store, "Stopped Book")
    finally:
        store.close()

    status = build_queue_status(db)

    assert status["running"] is False
    assert status["book"] is None
    assert status["job"] is None
    assert status["progress"]["chunks"] == 0
    assert status["heartbeat_age_s"] is None
    assert status["stale"] is False
    assert status["next_pending"]["id"] == book_id
    assert any(item["kind"] == "runner_stopped" for item in status["blockers"])


def test_missing_db_is_reported_without_creating_it(tmp_path: Path):
    db = tmp_path / "missing.db"

    status = build_queue_status(db)

    assert status["running"] is False
    assert status["book"] is None
    assert status["next_pending"] is None
    assert status["db"] == {"integrity": "missing", "journal_mode": None}
    assert any(item["kind"] == "db_missing" for item in status["blockers"])
    assert not db.exists()


def test_old_heartbeat_marks_the_status_stale(tmp_path: Path):
    db = tmp_path / "queue.db"
    _active_book(db, age_seconds=600, created_seconds=1200)

    status = build_queue_status(db, stale_after_s=120)

    assert status["running"] is True
    assert status["stale"] is True
    assert status["heartbeat_age_s"] is not None
    assert status["heartbeat_age_s"] >= 500
    assert any(item["kind"] == "stale_heartbeat" for item in status["blockers"])


def test_status_does_not_write_to_the_database(tmp_path: Path):
    db = tmp_path / "queue.db"
    _active_book(db)
    before_hash = hashlib.sha256(db.read_bytes()).hexdigest()
    before_mtime = db.stat().st_mtime_ns
    before_files = {path.name for path in db.parent.iterdir()}

    build_queue_status(db)

    assert hashlib.sha256(db.read_bytes()).hexdigest() == before_hash
    assert db.stat().st_mtime_ns == before_mtime
    assert {path.name for path in db.parent.iterdir()} == before_files
    assert not (db.with_name(db.name + "-wal")).exists()
    assert not (db.with_name(db.name + "-journal")).exists()


def test_cli_status_json(tmp_path: Path):
    db = tmp_path / "queue.db"
    book_id, _ = _active_book(db)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.literary.cli",
            "queue",
            "status",
            "--json",
            "--db",
            str(db),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    status = json.loads(completed.stdout)
    assert status["schema_version"] == "1.0"
    assert status["running"] is True
    assert status["book"]["id"] == book_id


def _write_supervisor_file(db: Path) -> Path:
    path = db.with_name("literary_queue.supervisor.json")
    path.write_text(
        json.dumps(
            {
                "schema": "literary-queue.supervisor",
                "schema_version": "1.0",
                "pid": 111,
                "heartbeat": "2026-11-11T16:00:00+00:00",
                "state": "backoff",
                "message": "backoff 60s after worker_died",
                "worker": {"pid": 222, "running": False},
                "restart": {
                    "attempts_last_hour": 1,
                    "max_per_hour": 3,
                    "last_reason": "worker_died",
                    "last_at": "2026-11-11T15:59:00+00:00",
                    "next_attempt_at": "2026-11-11T16:01:00+00:00",
                    "backoff_s": 60,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_status_reports_the_supervisor_restart_reason(tmp_path: Path):
    db = tmp_path / "queue.db"
    store = QueueStore(str(db))
    store.close()
    _write_supervisor_file(db)

    status = build_queue_status(db)

    assert status["supervisor"]["online"] is True
    assert status["supervisor"]["state"] == "backoff"
    assert status["supervisor"]["worker_running"] is False
    assert status["supervisor"]["restart"]["last_reason"] == "worker_died"
    assert status["supervisor"]["restart"]["attempts_last_hour"] == 1
    assert status["supervisor"]["restart"]["max_per_hour"] == 3


def test_stale_supervisor_file_is_offline(tmp_path: Path):
    db = tmp_path / "queue.db"
    store = QueueStore(str(db))
    store.close()
    path = _write_supervisor_file(db)
    old = time.time() - 600
    os.utime(path, (old, old))

    status = build_queue_status(db)

    assert status["supervisor"]["online"] is False
    assert status["supervisor"]["heartbeat_age_s"] >= 500


def test_missing_supervisor_file_is_reported_as_absent(tmp_path: Path):
    status = build_queue_status(tmp_path / "missing.db")

    assert status["supervisor"] is None
