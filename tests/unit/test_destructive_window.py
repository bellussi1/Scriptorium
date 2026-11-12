"""Window-mode phases of the 24 h destructive runner. Mock-tested: no Docker, no live queue."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "destructive_24h", ROOT / "tests" / "standalone" / "destructive_24h.py"
)
destructive = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(destructive)

ALL_OK = {name: True for name in destructive.CRITERIA_NAMES}


def _clock():
    state = {"t": 0.0}

    def now() -> float:
        return state["t"]

    def sleep(seconds: float) -> None:
        state["t"] += seconds

    return now, sleep


def _queue_with_one_book(db: Path) -> int:
    from src.literary.models import BookRecord
    from src.literary.queue import QueueStore

    db.parent.mkdir(parents=True, exist_ok=True)
    store = QueueStore(str(db))
    try:
        book_id = store.add_book(
            BookRecord(calibre_id=1, title="Probe", author="Test", languages=["en"], epub_path=""),
            priority=1,
        )
        store.create_job(book_id, total_chapters=6)
    finally:
        store.close()
    return book_id


def _set_job_state(db: Path, state: str) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute("UPDATE jobs SET state = ?", (state,))
        conn.commit()
    finally:
        conn.close()


def test_scratch_path_accepts_a_file_inside_the_root(tmp_path):
    inside = tmp_path / "scratch" / "queue.db"
    assert destructive.scratch_path(inside, tmp_path / "scratch") == inside.resolve()


def test_scratch_path_refuses_a_file_outside_the_root(tmp_path):
    with pytest.raises(ValueError):
        destructive.scratch_path(tmp_path / "elsewhere.db", tmp_path / "scratch")


def test_scratch_path_refuses_the_live_queue_even_under_a_wide_root():
    with pytest.raises(ValueError):
        destructive.scratch_path(destructive.LIVE_DB, destructive.ROOT)


def test_scratch_snapshot_reports_a_translating_job(tmp_path):
    db = tmp_path / "queue.db"
    _queue_with_one_book(db)
    _set_job_state(db, "translating")
    snap = destructive.scratch_snapshot(db, tmp_path / "outputs")
    assert snap["translating"] is True
    assert snap["criteria"] == ALL_OK


def test_scratch_snapshot_reports_no_translation_when_idle(tmp_path):
    db = tmp_path / "queue.db"
    _queue_with_one_book(db)
    _set_job_state(db, "pending")
    assert destructive.scratch_snapshot(db, tmp_path / "outputs")["translating"] is False


def _restart_run(calls):
    def run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    return run


def test_restart_phase_fails_when_nothing_was_translating():
    now, sleep = _clock()
    calls: list = []
    result = destructive.window_restart_phase(
        snapshot=lambda: {"translating": False, "criteria": dict(ALL_OK)},
        run=_restart_run(calls),
        health=lambda _c: "healthy",
        sleep=sleep,
        now=now,
    )
    assert result["was_translating"] is False
    assert result["passed"] is False


def test_restart_phase_passes_mid_translation_with_a_healthy_container():
    now, sleep = _clock()
    calls: list = []
    result = destructive.window_restart_phase(
        snapshot=lambda: {"translating": True, "criteria": dict(ALL_OK)},
        run=_restart_run(calls),
        health=lambda _c: "healthy",
        sleep=sleep,
        now=now,
    )
    assert result["passed"] is True
    assert calls == [
        ["docker", "compose", "-f", str(destructive.DEDICATED_COMPOSE), "restart", "app-destructive"]
    ]


def test_restart_phase_only_restarts_the_dedicated_service():
    now, sleep = _clock()
    calls: list = []
    destructive.window_restart_phase(
        snapshot=lambda: {"translating": True, "criteria": dict(ALL_OK)},
        run=_restart_run(calls),
        health=lambda _c: "healthy",
        sleep=sleep,
        now=now,
    )
    assert all(str(destructive.DEDICATED_COMPOSE) in command for command in calls)
    assert all(destructive.LIVE_CONTAINER not in command for command in calls)


def test_restart_phase_fails_when_the_container_never_becomes_healthy():
    now, sleep = _clock()
    result = destructive.window_restart_phase(
        snapshot=lambda: {"translating": True, "criteria": dict(ALL_OK)},
        run=_restart_run([]),
        health=lambda _c: "starting",
        sleep=sleep,
        now=now,
        timeout=10,
    )
    assert result["status"] == "starting"
    assert result["passed"] is False


def test_restart_phase_fails_when_criteria_break_after_the_restart():
    now, sleep = _clock()
    snapshots = iter(
        [
            {"translating": True, "criteria": dict(ALL_OK)},
            {"translating": False, "criteria": dict(ALL_OK, no_duplicate_suffix=False)},
        ]
    )
    result = destructive.window_restart_phase(
        snapshot=lambda: next(snapshots),
        run=_restart_run([]),
        health=lambda _c: "healthy",
        sleep=sleep,
        now=now,
    )
    assert result["passed"] is False


def test_corruption_phase_fails_closed_and_restores_the_queue(tmp_path):
    root = tmp_path / "scratch"
    db = root / "data" / "literary_queue.db"
    _queue_with_one_book(db)
    outputs = root / "outputs"
    outputs.mkdir(parents=True)
    result = destructive.window_corruption_phase(db, outputs, root=root)
    assert result["failed_loudly"] is True
    assert result["new_outputs"] == []
    assert result["restored_criteria"] == ALL_OK
    assert result["passed"] is True
    assert destructive.evaluate_criteria(db, outputs)["no_state_without_checkpoint"] is True


def test_corruption_phase_refuses_a_database_outside_the_scratch_area(tmp_path):
    outside = tmp_path / "elsewhere" / "queue.db"
    _queue_with_one_book(outside)
    before = outside.read_bytes()
    with pytest.raises(ValueError):
        destructive.window_corruption_phase(outside, tmp_path / "outputs", root=tmp_path / "scratch")
    assert outside.read_bytes() == before


def test_soak_phase_runs_for_the_requested_hours_when_criteria_hold():
    now, sleep = _clock()
    result = destructive.window_soak_phase(
        hours=1,
        interval=600,
        sample=lambda: dict(ALL_OK),
        now=now,
        sleep=sleep,
    )
    assert result["passed"] is True
    assert result["samples"] == 7
    assert result["elapsed_seconds"] == 3600.0


def test_soak_phase_stops_at_the_first_failed_sample():
    now, sleep = _clock()
    verdicts = [dict(ALL_OK), dict(ALL_OK), dict(ALL_OK, no_job_stuck_running=False)]
    result = destructive.window_soak_phase(
        hours=24,
        interval=300,
        sample=lambda: verdicts.pop(0),
        now=now,
        sleep=sleep,
    )
    assert result["passed"] is False
    assert result["samples"] == 3
    assert result["failures"][0]["failed"] == ["no_job_stuck_running"]


def test_run_window_refuses_without_confirmation():
    args = argparse.Namespace(
        confirm_window=False, compose="docker-compose.destructive.yml", soak_hours=24.0, soak_interval=300.0
    )
    assert destructive._run_window(args) == 2


def test_run_window_refuses_a_non_positive_soak():
    args = argparse.Namespace(
        confirm_window=True,
        compose=str(destructive.DEDICATED_COMPOSE),
        soak_hours=0,
        soak_interval=300.0,
    )
    assert destructive._run_window(args) == 2


def _window_args():
    return argparse.Namespace(
        confirm_window=True,
        compose=str(destructive.DEDICATED_COMPOSE),
        soak_hours=1.0,
        soak_interval=600.0,
    )


def _stub_window(monkeypatch, tmp_path, *, health="healthy", restart=None):
    scratch = tmp_path / "scratch"
    _queue_with_one_book(scratch / "data" / "literary_queue.db")
    monkeypatch.setattr(destructive, "ROOT", tmp_path)
    monkeypatch.setattr(destructive, "WINDOW_ROOT", scratch)
    monkeypatch.setattr(destructive, "scratch_path", lambda path, root=None: path)
    monkeypatch.setattr(destructive, "_app_health", lambda container=None: health)
    monkeypatch.setattr(destructive, "_pause_control_phase", lambda work: {"passed": True})
    monkeypatch.setattr(
        destructive,
        "window_restart_phase",
        restart or (lambda **kwargs: {"passed": True}),
    )
    monkeypatch.setattr(
        destructive, "window_corruption_phase", lambda db, outputs, **kwargs: {"passed": True}
    )
    monkeypatch.setattr(destructive, "window_soak_phase", lambda **kwargs: {"passed": True})


def test_run_window_writes_a_passing_report(tmp_path, monkeypatch):
    _stub_window(monkeypatch, tmp_path)
    assert destructive._run_window(_window_args()) == 0
    reports = list((tmp_path / "data" / "tmp").glob("destructive-24h-*/report.json"))
    assert len(reports) == 1
    assert set(json.loads(reports[0].read_text(encoding="utf-8"))["phases"]) == {
        "pause_control",
        "app_restart",
        "db_corruption",
        "soak",
    }


def test_run_window_fails_when_a_phase_fails(tmp_path, monkeypatch):
    _stub_window(monkeypatch, tmp_path, restart=lambda **kwargs: {"passed": False})
    assert destructive._run_window(_window_args()) == 1


def test_run_window_records_a_raising_phase_as_failed(tmp_path, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("docker is down")

    _stub_window(monkeypatch, tmp_path, restart=broken)
    assert destructive._run_window(_window_args()) == 1


def test_run_window_needs_the_dedicated_app_healthy(tmp_path, monkeypatch):
    _stub_window(monkeypatch, tmp_path, health="starting")
    assert destructive._run_window(_window_args()) == 2
