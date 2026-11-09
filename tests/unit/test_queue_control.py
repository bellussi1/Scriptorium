"""Pause-after-book control file used by the web UI and the queue runner."""
from __future__ import annotations

from pathlib import Path

from src.literary.queue_control import (
    control_path,
    honor_pause,
    pause_requested,
    read_control,
    set_pause,
)


def test_control_file_lives_next_to_the_queue_database(tmp_path: Path):
    db = tmp_path / "literary_queue.db"
    assert control_path(db) == tmp_path / "literary_queue.control.json"


def test_missing_control_file_reads_as_idle(tmp_path: Path):
    state = read_control(tmp_path / "queue.db")
    assert state == {
        "pause_after_book": False,
        "requested_at": None,
        "honored_at": None,
        "honored_after": None,
    }


def test_requesting_a_pause_writes_and_reads_back(tmp_path: Path):
    db = tmp_path / "queue.db"
    state = set_pause(db, True)

    assert state["pause_after_book"] is True
    assert state["requested_at"]
    assert pause_requested(db) is True
    assert control_path(db).is_file()

    stored = read_control(db)
    assert stored["pause_after_book"] is True
    assert stored["requested_at"] == state["requested_at"]


def test_cancelling_a_pause_clears_the_request(tmp_path: Path):
    db = tmp_path / "queue.db"
    set_pause(db, True)

    state = set_pause(db, False)

    assert state["pause_after_book"] is False
    assert state["requested_at"] is None
    assert pause_requested(db) is False


def test_honouring_a_pause_records_the_book_and_clears_the_flag(tmp_path: Path):
    db = tmp_path / "queue.db"
    set_pause(db, True)

    state = honor_pause(db, {"id": 7, "title": "The Mad Ship"})

    assert state["pause_after_book"] is False
    assert state["honored_at"]
    assert state["honored_after"] == {"id": 7, "title": "The Mad Ship"}
    assert pause_requested(db) is False


def test_honouring_without_a_request_is_a_no_op(tmp_path: Path):
    db = tmp_path / "queue.db"
    state = honor_pause(db, {"id": 1, "title": "Book"})

    assert state["pause_after_book"] is False
    assert state["honored_at"] is None
    assert not control_path(db).exists()


def test_corrupt_control_file_reads_as_idle(tmp_path: Path):
    db = tmp_path / "queue.db"
    control_path(db).write_text("{not json", encoding="utf-8")

    assert read_control(db)["pause_after_book"] is False
    assert pause_requested(db) is False
