"""Tests for the auto_queue supervisor decisions and limits."""
from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "auto_queue", ROOT / "scripts" / "auto_queue.py"
)
assert SPEC and SPEC.loader
auto_queue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto_queue)


def test_gate_is_a_hold_not_a_restart():
    action, reason = auto_queue._classify_exit(
        1, {"reason": "gate_needs_review"}, False
    )

    assert action == "hold"
    assert reason == "gate_needs_review"


def test_needs_review_is_a_hold_too():
    action, reason = auto_queue._classify_exit(1, {"reason": "needs_review"}, False)

    assert action == "hold"


def test_failed_book_stops_the_supervisor():
    action, _ = auto_queue._classify_exit(1, {"reason": "failed_book"}, False)

    assert action == "stop"


def test_budget_stops_without_restarting():
    action, _ = auto_queue._classify_exit(1, {"reason": "budget"}, False)

    assert action == "stop"


def test_clean_idle_exit_stops():
    action, reason = auto_queue._classify_exit(0, {"reason": "no_pending"}, False)

    assert action == "stop"
    assert reason == "no_pending"


def test_runner_failure_restarts():
    action, reason = auto_queue._classify_exit(1, {"reason": "runner_failed"}, False)

    assert action == "restart"
    assert reason == "runner_failed"


def test_killed_worker_becomes_worker_died():
    action, reason = auto_queue._classify_exit(1, {"reason": "active"}, False)

    assert action == "restart"
    assert reason == "worker_died"


def test_stall_without_status_restarts_as_stalled():
    action, reason = auto_queue._classify_exit(-1, {}, True)

    assert action == "restart"
    assert reason == "worker_stalled"


def test_backoff_doubles_and_caps():
    assert auto_queue._backoff_seconds(1, 30, 900) == 30
    assert auto_queue._backoff_seconds(2, 30, 900) == 60
    assert auto_queue._backoff_seconds(5, 30, 900) == 480
    assert auto_queue._backoff_seconds(10, 30, 900) == 900


def test_restart_history_keeps_only_the_last_hour():
    now = time.time()
    history = [
        datetime.fromtimestamp(now - 7200, timezone.utc).isoformat(timespec="seconds"),
        datetime.fromtimestamp(now - 60, timezone.utc).isoformat(timespec="seconds"),
        datetime.fromtimestamp(now - 10, timezone.utc).isoformat(timespec="seconds"),
    ]

    recent = auto_queue._recent_attempts(now, history)

    assert len(recent) == 2


def test_budget_blocks_after_the_hourly_limit():
    now = time.time()
    history = [
        datetime.fromtimestamp(now - 180, timezone.utc).isoformat(timespec="seconds"),
        datetime.fromtimestamp(now - 120, timezone.utc).isoformat(timespec="seconds"),
        datetime.fromtimestamp(now - 60, timezone.utc).isoformat(timespec="seconds"),
    ]
    old = [
        datetime.fromtimestamp(now - 7200, timezone.utc).isoformat(timespec="seconds")
    ] * 3

    assert auto_queue._budget_exhausted(history, 3) is True
    assert auto_queue._budget_exhausted(history[:2], 3) is False
    assert auto_queue._budget_exhausted(old, 3) is False


def test_heartbeat_age_matches_windows_venv_shim_ppid(monkeypatch, tmp_path):
    status_path = tmp_path / "literary_queue.auto.json"
    monkeypatch.setattr(auto_queue, "STATUS_PATH", status_path)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status_path.write_text(
        json.dumps({"pid": 99999, "ppid": 4242, "heartbeat": started}),
        encoding="utf-8",
    )

    age = auto_queue._heartbeat_age(4242, started)
    assert age is not None and age >= 0.0
    assert auto_queue._status_matches_worker({"pid": 99999, "ppid": 4242}, 4242) is True
    assert auto_queue._status_matches_worker({"pid": 99999, "ppid": 4242}, 1111) is False


def test_atomic_write_retries_permission_error(monkeypatch, tmp_path):
    target = tmp_path / "status.json"
    real_replace = os.replace
    attempts = {"count": 0}

    def flaky_replace(src, dst):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("simulated WinError 5")
        return real_replace(src, dst)

    monkeypatch.setattr(auto_queue.os, "replace", flaky_replace)
    monkeypatch.setattr(auto_queue.time, "sleep", lambda _s: None)

    auto_queue._atomic_write(target, {"ok": True})

    assert attempts["count"] == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    assert list(tmp_path.glob(".*.tmp")) == []

