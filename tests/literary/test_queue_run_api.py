"""HTTP contract for the Queue UI's Run buttons."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from flask import Flask

from src.api.blueprints.literary_queue_routes import create_literary_queue_blueprint
from src.literary.models import BookRecord
from src.literary.queue import QueueStore

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
    db = tmp_path / "queue.db"
    store = QueueStore(str(db))
    book_id = store.add_book(_record(make_epub(tmp_path / "book.epub")))
    store.close()
    monkeypatch.setenv("LITERARY_QUEUE_DB", str(db))
    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())
    return app.test_client(), db, book_id


def test_run_writes_a_request_for_the_host_agent(queue):
    client, db, book_id = queue

    response = client.post("/api/literary/queue/run", json={"mode": "next"})

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["run_request"]["mode"] == "next"
    assert payload["agent"]["online"] is False
    assert (db.parent / "queue.run-request.json").exists()

    conn = sqlite3.connect(db)
    try:
        message = conn.execute(
            "SELECT message FROM events WHERE book_id = ? ORDER BY id DESC LIMIT 1",
            (book_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert "queue run requested" in message


def test_runner_endpoint_exposes_the_pending_request(queue):
    client, _db, _book_id = queue
    client.post("/api/literary/queue/run", json={"mode": "all"})

    response = client.get("/api/literary/queue/runner")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["run_request"]["mode"] == "all"
    assert payload["agent"]["online"] is False


def test_run_rejects_invalid_mode(queue):
    client, _db, _book_id = queue

    response = client.post("/api/literary/queue/run", json={"mode": "sideways"})

    assert response.status_code == 400


def test_run_rejects_an_empty_queue(queue, tmp_path, monkeypatch):
    client, _db, _book_id = queue
    empty = tmp_path / "empty.db"
    QueueStore(str(empty)).close()
    monkeypatch.setenv("LITERARY_QUEUE_DB", str(empty))

    response = client.post("/api/literary/queue/run", json={"mode": "next"})

    assert response.status_code == 409
