"""`queue run-all` honours the pause-after-book control between books."""
from __future__ import annotations

import argparse
from pathlib import Path

import sqlite3

from src.literary.cli import cmd_queue_run_all
from src.literary.models import BookRecord
from src.literary.queue import QueueStore
from src.literary.queue_control import read_control, set_pause
from src.literary.queue_runner import active_direct_translation


def _args(db: Path, **overrides) -> argparse.Namespace:
    values = {
        "db": str(db),
        "resources": "literary-resources",
        "refine_limit": 0,
        "no_refine": False,
        "pov": "",
        "parallel": 1,
        "max_books": 1,
        "stop_on_review": False,
        "stop_on_error": False,
        "export_kindle": False,
        "outputs": "translated_files",
        "kindle_out": "translated_files/kindle",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _seed(db: Path, calibre_id: int, title: str) -> int:
    epub = db.parent / f"{calibre_id}.epub"
    epub.write_bytes(b"fake epub")
    store = QueueStore(str(db))
    try:
        return store.add_book(
            BookRecord(
                calibre_id=calibre_id,
                title=title,
                author="Test Author",
                languages=["en"],
                epub_path=str(epub),
            )
        )
    finally:
        store.close()


def _complete_run(db_path: str, book_id: int, **kwargs) -> dict:
    store = QueueStore(db_path)
    try:
        store.set_book_state(book_id, "paused", "stub run finished")
    finally:
        store.close()
    return {"queue_state": "paused"}


def test_a_pre_set_pause_stops_before_starting_a_book(tmp_path: Path, monkeypatch):
    db = tmp_path / "queue.db"
    _seed(db, 1, "First")
    _seed(db, 2, "Second")
    set_pause(str(db), True)

    calls = []

    def fake_runner(db_path, book_id, **kwargs):
        calls.append(book_id)
        return _complete_run(db_path, book_id)

    monkeypatch.setattr("src.literary.queue_runner.run_queue_book", fake_runner)

    assert cmd_queue_run_all(_args(db)) == 0
    assert calls == []

    control = read_control(str(db))
    assert control["pause_after_book"] is False
    assert control["honored_after"] is None

    store = QueueStore(str(db))
    try:
        assert [book.id for book in store.list_books(status="pending")] == [1, 2]
    finally:
        store.close()


def test_a_pause_raised_during_a_book_stops_after_that_book(
    tmp_path: Path, monkeypatch
):
    db = tmp_path / "queue.db"
    first = _seed(db, 1, "First")
    second = _seed(db, 2, "Second")
    calls = []

    def fake_runner(db_path, book_id, **kwargs):
        calls.append(book_id)
        result = _complete_run(db_path, book_id)
        set_pause(db_path, True)
        return result

    monkeypatch.setattr("src.literary.queue_runner.run_queue_book", fake_runner)

    assert cmd_queue_run_all(_args(db)) == 0
    assert calls == [first]

    control = read_control(str(db))
    assert control["pause_after_book"] is False
    assert control["honored_after"] == {"id": first, "title": "First"}

    store = QueueStore(str(db))
    try:
        assert [book.id for book in store.list_books(status="pending")] == [second]
    finally:
        store.close()


def test_without_a_pause_the_runner_processes_exactly_one_book(
    tmp_path: Path, monkeypatch
):
    db = tmp_path / "queue.db"
    first = _seed(db, 1, "First")
    second = _seed(db, 2, "Second")
    calls = []

    def fake_runner(db_path, book_id, **kwargs):
        calls.append(book_id)
        return _complete_run(db_path, book_id)

    monkeypatch.setattr("src.literary.queue_runner.run_queue_book", fake_runner)

    assert cmd_queue_run_all(_args(db)) == 0
    assert calls == [first]
    assert read_control(str(db))["honored_at"] is None

    store = QueueStore(str(db))
    try:
        assert [book.id for book in store.list_books(status="pending")] == [second]
    finally:
        store.close()


def test_batch_size_is_rejected(tmp_path: Path):
    db = tmp_path / "queue.db"
    _seed(db, 1, "First")

    assert cmd_queue_run_all(_args(db, max_books=2)) == 1


def test_parallel_slots_are_rejected(tmp_path: Path):
    db = tmp_path / "queue.db"
    _seed(db, 1, "First")

    assert cmd_queue_run_all(_args(db, parallel=2)) == 1


def test_a_paused_result_stops_the_run_all_loop(tmp_path: Path, monkeypatch):
    db = tmp_path / "queue.db"
    _seed(db, 1, "First")
    second = _seed(db, 2, "Second")
    calls = []

    def fake_runner(db_path, book_id, **kwargs):
        calls.append(book_id)
        _complete_run(db_path, book_id)
        return {"queue_state": "paused", "paused": True}

    monkeypatch.setattr("src.literary.queue_runner.run_queue_book", fake_runner)

    assert cmd_queue_run_all(_args(db)) == 0
    assert len(calls) == 1

    store = QueueStore(str(db))
    try:
        assert [book.id for book in store.list_books(status="pending")] == [second]
    finally:
        store.close()


def test_active_direct_translation_detects_a_recent_running_job(tmp_path: Path):
    jobs = tmp_path / "jobs.db"
    conn = sqlite3.connect(jobs)
    try:
        conn.execute(
            "CREATE TABLE translation_jobs "
            "(translation_id TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO translation_jobs VALUES ('web_1', 'running', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO translation_jobs VALUES "
            "('web_old', 'running', datetime('now', '-30 minutes'))"
        )
        conn.execute(
            "INSERT INTO translation_jobs VALUES "
            "('cli_queue_job', 'running', datetime('now'))"
        )
        conn.commit()
    finally:
        conn.close()

    assert active_direct_translation(jobs) == "web_1"
    assert active_direct_translation(jobs, exclude_translation_id="web_1") is None
