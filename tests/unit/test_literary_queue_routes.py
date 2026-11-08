"""Tests for the read-only literary queue API."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask

from src.api.blueprints.literary_queue_routes import (
    build_queue_snapshot,
    create_literary_queue_blueprint,
)


def _queue_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            calibre_id INTEGER,
            title TEXT,
            author TEXT,
            series TEXT,
            series_index REAL,
            status TEXT,
            word_count INTEGER,
            model TEXT,
            provider TEXT,
            priority INTEGER DEFAULT 0
        );
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            book_id INTEGER,
            state TEXT,
            translation_id TEXT,
            current_chapter INTEGER,
            total_chapters INTEGER,
            error TEXT,
            updated_at TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            level TEXT,
            message TEXT,
            created_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO books VALUES (1, 100, 'Howling Dark', 'Christopher Ruocchio', "
        "'The Sun Eater', 2.0, 'translating', 264961, 'hy-mt2', 'ollama', 0)"
    )
    conn.execute(
        "INSERT INTO books VALUES (2, 101, 'Demon in White', 'Christopher Ruocchio', "
        "'The Sun Eater', 3.0, 'pending', 295868, 'hy-mt2', 'ollama', 0)"
    )
    conn.execute(
        "INSERT INTO jobs VALUES (1, 1, 'translating', 'cli_test', 10, 100, '', "
        "'2026-11-08T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO events (level, message, created_at) VALUES "
        "('info', 'full-book translation started: cli_test', '2026-11-08T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


def test_snapshot_summarizes_books_jobs_and_events(tmp_path: Path):
    db = tmp_path / "queue.db"
    _queue_db(db)

    snapshot = build_queue_snapshot(db)

    assert snapshot["status"] == "ok"
    assert snapshot["summary"]["books"] == 2
    assert snapshot["summary"]["words"] == 560829
    assert snapshot["summary"]["by_status"] == {"translating": 1, "pending": 1}
    first = snapshot["books"][0]
    assert first["title"] == "Howling Dark"
    assert first["job_state"] == "translating"
    assert first["translation_id"] == "cli_test"
    assert first["current_chapter"] == 10
    assert first["total_chapters"] == 100
    assert "source_path" not in first
    assert snapshot["events"][0]["message"].startswith("full-book translation")


def test_missing_database_is_an_empty_queue(tmp_path: Path):
    snapshot = build_queue_snapshot(tmp_path / "missing.db")
    assert snapshot["status"] == "empty"
    assert snapshot["books"] == []
    assert snapshot["summary"]["books"] == 0


def test_route_returns_json(tmp_path: Path, monkeypatch):
    db = tmp_path / "queue.db"
    _queue_db(db)
    monkeypatch.setenv("LITERARY_QUEUE_DB", str(db))

    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())
    response = app.test_client().get("/api/literary/queue")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["summary"]["books"] == 2
    assert payload["books"][0]["translation_id"] == "cli_test"
