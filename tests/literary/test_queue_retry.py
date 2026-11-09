"""Queue retry must keep a usable checkpoint and release a broken one."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from flask import Flask

from src.api.blueprints.literary_queue_routes import create_literary_queue_blueprint
from src.literary.models import BookRecord
from src.literary.queue import QueueStore
from src.persistence.checkpoint_manager import CheckpointManager

from .conftest import make_epub


def _record(path: Path) -> BookRecord:
    return BookRecord(
        calibre_id=1,
        title="Test Book",
        author="Test Author",
        series="Test Series",
        series_index=1.0,
        languages=["en"],
        formats=["EPUB"],
        epub_path=str(path),
    )


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = QueueStore(str(tmp_path / "queue.db"))
    book_id = store.add_book(_record(make_epub(tmp_path / "book.epub")))
    job_id = store.create_job(book_id, total_chapters=10)
    store.attach_translation_id(job_id, "cli_test")
    store.set_book_state(book_id, "paused")
    store.set_job_state(job_id, "paused")
    conn = sqlite3.connect(tmp_path / "queue.db")
    conn.execute(
        "UPDATE jobs SET current_chapter = 4, total_chapters = 10 WHERE id = ?",
        (job_id,),
    )
    conn.commit()
    conn.close()
    store.close()

    monkeypatch.setenv("LITERARY_QUEUE_DB", str(tmp_path / "queue.db"))
    monkeypatch.setenv("JOBS_DB_PATH", str(tmp_path / "jobs.db"))
    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())
    return app.test_client(), tmp_path / "queue.db", book_id, job_id


def _row(db: Path, table: str, where: str, params=()):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(f"SELECT * FROM {table} WHERE {where}", params).fetchone()
    finally:
        conn.close()


def test_retry_releases_a_stale_checkpoint(queue):
    client, db, book_id, job_id = queue

    response = client.post(f"/api/literary/queue/books/{book_id}/retry")

    assert response.status_code == 200
    book = _row(db, "books", "id = ?", (book_id,))
    job = _row(db, "jobs", "id = ?", (job_id,))
    assert book["status"] == "pending"
    assert job["state"] == "paused"
    assert job["translation_id"] == ""
    assert job["current_chapter"] == 0
    assert job["total_chapters"] == 0


def test_retry_keeps_a_resumable_checkpoint(queue):
    client, db, book_id, job_id = queue
    source = Path("data") / "uploads" / "cli_test" / "Book.epub"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    manager = CheckpointManager(db_path=str(Path("jobs.db").resolve()))
    try:
        manager.db.create_job(
            "cli_test", "epub", {"preserved_input_path": str(source)}
        )
        manager.db.save_chunk("cli_test", 0, "source", "target")
        manager.db.update_job_progress(
            "cli_test", total_chunks=10, completed_chunks=1, status="paused"
        )
    finally:
        manager.close()

    response = client.post(f"/api/literary/queue/books/{book_id}/retry")

    assert response.status_code == 200
    book = _row(db, "books", "id = ?", (book_id,))
    job = _row(db, "jobs", "id = ?", (job_id,))
    assert book["status"] == "pending"
    assert job["translation_id"] == "cli_test"
    assert job["current_chapter"] == 4
    assert job["total_chapters"] == 10
