"""Tests for the auto_queue supervisor decisions and limits."""
from __future__ import annotations

import importlib.util
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
