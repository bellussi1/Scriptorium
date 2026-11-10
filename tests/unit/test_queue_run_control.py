"""File channel shared by the Queue UI and the host runner agent."""
from __future__ import annotations

import os
import time

import pytest

from src.literary.queue_run_control import (
    agent_status_path,
    clear_run_request,
    read_agent_status,
    read_run_request,
    read_runner_info,
    request_path,
    request_run,
    runner_info_path,
    write_agent_status,
    write_runner_info,
)


def test_request_run_round_trip(tmp_path):
    db = tmp_path / "queue.db"

    payload = request_run(db, mode="next", requested_by="test")

    assert payload["mode"] == "next"
    assert request_path(db).exists()
    assert read_run_request(db)["mode"] == "next"

    honored = clear_run_request(db, "started")
    assert honored["mode"] == "next"
    assert honored["message"] == "started"
    assert honored["honored_at"]
    assert read_run_request(db) is None
    assert not request_path(db).exists()


def test_request_run_rejects_unknown_mode(tmp_path):
    with pytest.raises(ValueError):
        request_run(tmp_path / "queue.db", mode="sideways")


def test_request_run_rejects_batch_mode(tmp_path):
    with pytest.raises(ValueError):
        request_run(tmp_path / "queue.db", mode="all")


def test_agent_status_is_online_while_heartbeat_is_fresh(tmp_path):
    db = tmp_path / "queue.db"
    write_agent_status(db, {"message": "agent online"})

    status = read_agent_status(db)
    assert status["online"] is True
    assert status["pid"] == os.getpid()

    old = time.time() - 60
    os.utime(agent_status_path(db), (old, old))
    stale = read_agent_status(db)
    assert stale["online"] is False
    assert stale["heartbeat_age_s"] >= 50


def test_agent_status_missing_is_offline(tmp_path):
    status = read_agent_status(tmp_path / "queue.db")
    assert status["online"] is False


def test_status_write_retries_when_windows_reader_holds_the_file(tmp_path, monkeypatch):
    import src.literary.queue_run_control as control

    original_replace = control.os.replace
    calls = {"count": 0}

    def flaky_replace(source, destination):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("file is open in another process")
        return original_replace(source, destination)

    monkeypatch.setattr(control.os, "replace", flaky_replace)
    db = tmp_path / "queue.db"

    write_agent_status(db, {"message": "agent online"})

    assert calls["count"] == 3
    assert read_agent_status(db)["message"] == "agent online"


def test_runner_info_round_trip(tmp_path):
    db = tmp_path / "queue.db"
    write_runner_info(db, {"runner_pid": 123, "running": True, "title": "Book"})

    assert runner_info_path(db).exists()
    assert read_runner_info(db)["runner_pid"] == 123
    assert read_runner_info(db)["running"] is True
