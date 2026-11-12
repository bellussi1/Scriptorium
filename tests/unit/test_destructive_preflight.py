"""Preflight rules of the 24 h destructive runner. Nothing here touches the live stack."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "destructive_24h", ROOT / "tests" / "standalone" / "destructive_24h.py"
)
destructive = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(destructive)

IDLE = {
    "active_books": [],
    "runner_running": False,
    "container_top": "PID USER COMMAND\n1 root bash",
    "container_error": False,
}


def test_idle_stack_has_no_reasons():
    assert destructive.live_activity([], False, "1 root bash") == []


def test_active_book_blocks():
    assert destructive.live_activity(["Disquiet Gods"], False, "") == [
        "book in an active state: Disquiet Gods"
    ]


def test_running_runner_blocks():
    assert any("runner" in reason for reason in destructive.live_activity([], True, ""))


def test_translate_process_in_live_container_blocks():
    top = "1 root python translate.py -i book.epub"
    assert any("translate.py" in reason for reason in destructive.live_activity([], False, top))


def test_idle_short_mode_is_ready(monkeypatch):
    monkeypatch.setattr(destructive, "_read_live_state", lambda: dict(IDLE))
    assert destructive.preflight("short", None)["ready"] is True


def test_busy_short_mode_is_not_ready(monkeypatch):
    busy = dict(IDLE, active_books=["Disquiet Gods"])
    monkeypatch.setattr(destructive, "_read_live_state", lambda: busy)
    result = destructive.preflight("short", None)
    assert result["ready"] is False
    assert result["reasons"] == ["book in an active state: Disquiet Gods"]


def test_uninspectable_container_is_not_ready(monkeypatch):
    unknown = dict(IDLE, container_error=True, container_top="")
    monkeypatch.setattr(destructive, "_read_live_state", lambda: unknown)
    result = destructive.preflight("short", None)
    assert result["ready"] is False
    assert any("cannot inspect" in reason for reason in result["reasons"])


def test_window_mode_needs_the_dedicated_compose(monkeypatch):
    monkeypatch.setattr(destructive, "_read_live_state", lambda: dict(IDLE))
    result = destructive.preflight("window", None)
    assert result["ready"] is False
    assert any("dedicated compose" in reason for reason in result["reasons"])


def _queue_with_one_book(tmp_path):
    from src.literary.models import BookRecord
    from src.literary.queue import QueueStore

    db = tmp_path / "queue.db"
    store = QueueStore(str(db))
    try:
        book_id = store.add_book(
            BookRecord(calibre_id=1, title="Probe", author="Test", languages=["en"], epub_path=""),
            priority=1,
        )
        job_id = store.create_job(book_id, total_chapters=6)
    finally:
        store.close()
    return db, book_id, job_id


def _set_state(db, book_id, job_id, book_status, job_state, checkpoint=None):
    import sqlite3

    conn = sqlite3.connect(db)
    try:
        conn.execute("UPDATE books SET status = ? WHERE id = ?", (book_status, book_id))
        conn.execute(
            "UPDATE jobs SET state = ?, checkpoint_json = ? WHERE id = ?", (job_state, checkpoint, job_id)
        )
        conn.commit()
    finally:
        conn.close()


def test_completed_book_with_full_checkpoint_passes(tmp_path):
    db, book_id, job_id = _queue_with_one_book(tmp_path)
    _set_state(db, book_id, job_id, "completed", "completed",
               '{"upstream_completed_chunks": 6, "upstream_total_chunks": 6}')
    verdict = destructive.evaluate_criteria(db, tmp_path / "outputs")
    assert verdict["no_state_without_checkpoint"] is True
    assert verdict["no_job_stuck_running"] is True
    assert verdict["no_duplicate_suffix"] is True


def test_completed_book_without_checkpoint_fails(tmp_path):
    db, book_id, job_id = _queue_with_one_book(tmp_path)
    _set_state(db, book_id, job_id, "completed", "completed", "{}")
    verdict = destructive.evaluate_criteria(db, tmp_path / "outputs")
    assert verdict["no_state_without_checkpoint"] is False


def test_review_book_with_an_active_job_is_stuck(tmp_path):
    db, book_id, job_id = _queue_with_one_book(tmp_path)
    _set_state(db, book_id, job_id, "needs_review", "translating", "{}")
    verdict = destructive.evaluate_criteria(db, tmp_path / "outputs")
    assert verdict["no_job_stuck_running"] is False


def test_duplicate_suffix_is_reported(tmp_path):
    db, book_id, job_id = _queue_with_one_book(tmp_path)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "Probe (pt-BR) (1).epub").write_bytes(b"x")
    verdict = destructive.evaluate_criteria(db, outputs)
    assert verdict["no_duplicate_suffix"] is False
