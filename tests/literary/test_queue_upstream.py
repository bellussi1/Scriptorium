"""Queue reconciliation with the upstream checkpoint database."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.literary.models import BookRecord
from src.literary.queue import QueueStore, _transition_path

from .conftest import make_epub


def _record(path: Path, calibre_id: int = 1, title: str = "Test Book") -> BookRecord:
    return BookRecord(
        calibre_id=calibre_id,
        title=title,
        author="Test Author",
        series="Test Series",
        series_index=float(calibre_id),
        languages=["en"],
        formats=["EPUB"],
        epub_path=str(path),
    )


def _upstream_db(path: Path, rows) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE translation_jobs (
            translation_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            file_type TEXT NOT NULL,
            config JSON NOT NULL,
            progress JSON NOT NULL,
            translation_context JSON,
            server_session_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paused_at TIMESTAMP,
            completed_at TIMESTAMP
        );
        """
    )
    for translation_id, status, progress in rows:
        conn.execute(
            "INSERT INTO translation_jobs "
            "(translation_id, status, file_type, config, progress) "
            "VALUES (?, ?, 'epub', '{}', ?)",
            (translation_id, status, json.dumps(progress)),
        )
    conn.commit()
    conn.close()


def _linked_job(tmp_path: Path, translation_id: str = "trans_test"):
    epub = make_epub(tmp_path / "book.epub")
    store = QueueStore(str(tmp_path / "queue.db"))
    book_id = store.add_book(_record(epub))
    job_id = store.create_job(book_id, total_chapters=10)
    assert store.attach_translation_id(job_id, translation_id)
    return store, book_id, job_id


def test_state_transition_paths_are_deterministic():
    assert _transition_path("pending", "translating") == ["preparing", "translating"]
    assert _transition_path("preparing", "validating") == ["translating", "validating"]
    assert _transition_path("completed", "translating") == []


def test_attach_and_lookup_translation_id(tmp_path: Path):
    store, book_id, job_id = _linked_job(tmp_path, "trans_abc")
    job = store.get_job(job_id)
    assert job["translation_id"] == "trans_abc"
    assert store.get_job_by_translation_id("trans_abc")["id"] == job_id
    assert store.get_job_by_translation_id("missing") is None
    listed = store.list_jobs()
    assert listed[0]["book_title"] == "Test Book"
    assert listed[0]["translation_id"] == "trans_abc"
    store.close()


def test_attach_rejects_conflicting_links(tmp_path: Path):
    store, book_id, job_id = _linked_job(tmp_path, "trans_one")
    other_book = store.add_book(_record(make_epub(tmp_path / "other.epub"), 2, "Other"))
    other_job = store.create_job(other_book, total_chapters=1)

    with pytest.raises(ValueError):
        store.attach_translation_id(other_job, "trans_one")
    with pytest.raises(ValueError):
        store.attach_translation_id(job_id, "trans_two")
    store.close()


def test_sync_running_job_maps_progress_and_state(tmp_path: Path):
    store, book_id, job_id = _linked_job(tmp_path)
    upstream = tmp_path / "jobs.db"
    _upstream_db(
        upstream,
        [
            (
                "trans_test",
                "running",
                {
                    "current_chunk_index": 3,
                    "total_chunks": 10,
                    "completed_chunks": 4,
                    "failed_chunks": 0,
                },
            )
        ],
    )

    report = store.sync_from_upstream(str(upstream))
    assert report["matched"] == 1
    assert report["updated"] == 1
    job = store.get_job(job_id)
    assert job["state"] == "translating"
    assert job["current_chapter"] == 4
    assert job["total_chapters"] == 10
    checkpoint = json.loads(job["checkpoint_json"])
    assert checkpoint["upstream_status"] == "running"
    assert checkpoint["upstream_completed_chunks"] == 4
    assert store.get_book(book_id).status == "translating"
    store.close()


def test_sync_is_idempotent(tmp_path: Path):
    store, _, job_id = _linked_job(tmp_path)
    upstream = tmp_path / "jobs.db"
    _upstream_db(
        upstream,
        [
            (
                "trans_test",
                "running",
                {"current_chunk_index": 1, "total_chunks": 5, "completed_chunks": 2, "failed_chunks": 0},
            )
        ],
    )
    first = store.sync_from_upstream(str(upstream))
    second = store.sync_from_upstream(str(upstream))
    assert first["updated"] == 1
    assert second["updated"] == 0
    assert store.get_job(job_id)["state"] == "translating"
    store.close()


@pytest.mark.parametrize(
    "upstream_status,queue_state",
    [
        ("completed", "validating"),
        ("partial", "needs_review"),
        ("error", "failed"),
        ("paused", "paused"),
        ("interrupted", "paused"),
    ],
)
def test_sync_maps_upstream_statuses(tmp_path: Path, upstream_status: str, queue_state: str):
    store, book_id, job_id = _linked_job(tmp_path)
    upstream = tmp_path / "jobs.db"
    _upstream_db(
        upstream,
        [
            (
                "trans_test",
                upstream_status,
                {"current_chunk_index": 2, "total_chunks": 4, "completed_chunks": 3, "failed_chunks": 0},
            )
        ],
    )
    store.sync_from_upstream(str(upstream))
    assert store.get_job(job_id)["state"] == queue_state
    assert store.get_book(book_id).status == queue_state
    store.close()


def test_sync_infers_completion_from_full_progress(tmp_path: Path):
    store, book_id, job_id = _linked_job(tmp_path)
    upstream = tmp_path / "jobs.db"
    _upstream_db(
        upstream,
        [
            (
                "trans_test",
                "running",
                {"current_chunk_index": 11, "total_chunks": 12, "completed_chunks": 12, "failed_chunks": 0},
            )
        ],
    )
    store.sync_from_upstream(str(upstream))
    job = store.get_job(job_id)
    assert job["state"] == "validating"
    checkpoint = json.loads(job["checkpoint_json"])
    assert checkpoint["upstream_status"] == "running"
    assert checkpoint["upstream_effective_status"] == "completed"
    assert store.get_book(book_id).status == "validating"
    store.close()


def test_sync_treats_full_progress_with_failures_as_needs_review(tmp_path: Path):
    store, _, job_id = _linked_job(tmp_path)
    upstream = tmp_path / "jobs.db"
    _upstream_db(
        upstream,
        [
            (
                "trans_test",
                "running",
                {"current_chunk_index": 11, "total_chunks": 12, "completed_chunks": 12, "failed_chunks": 1},
            )
        ],
    )
    store.sync_from_upstream(str(upstream))
    assert store.get_job(job_id)["state"] == "needs_review"
    store.close()


def test_completed_upstream_can_be_closed_after_validation(tmp_path: Path):
    store, book_id, job_id = _linked_job(tmp_path)
    upstream = tmp_path / "jobs.db"
    _upstream_db(
        upstream,
        [
            (
                "trans_test",
                "completed",
                {"current_chunk_index": 9, "total_chunks": 10, "completed_chunks": 10, "failed_chunks": 0},
            )
        ],
    )
    store.sync_from_upstream(str(upstream))
    assert store.get_job(job_id)["state"] == "validating"
    store.set_job_state(job_id, "completed", "validation passed")
    store.set_book_state(book_id, "completed", "validation passed")
    assert store.get_job(job_id)["state"] == "completed"
    assert store.get_book(book_id).status == "completed"
    store.close()


def test_sync_reports_unmatched_and_missing_database(tmp_path: Path):
    store, _, _ = _linked_job(tmp_path)
    upstream = tmp_path / "jobs.db"
    _upstream_db(
        upstream,
        [
            (
                "trans_other",
                "running",
                {"current_chunk_index": 0, "total_chunks": 1, "completed_chunks": 0, "failed_chunks": 0},
            )
        ],
    )
    report = store.sync_from_upstream(str(upstream))
    assert report["checked"] == 1
    assert report["matched"] == 0
    assert report["unmatched"] == ["trans_other"]
    missing = store.sync_from_upstream(str(tmp_path / "missing.db"))
    assert missing["error"] == "checkpoint database not found"
    store.close()


def test_existing_database_is_migrated_with_translation_id(tmp_path: Path):
    db_path = tmp_path / "old_queue.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            current_chapter INTEGER NOT NULL DEFAULT 0,
            total_chapters INTEGER NOT NULL DEFAULT 0,
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    store = QueueStore(str(db_path))
    with store._connect() as check:
        columns = {row["name"] for row in check.execute("PRAGMA table_info(jobs)")}
    assert "translation_id" in columns
    store.close()
