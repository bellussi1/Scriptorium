"""The single writer: intents are spooled by the app and applied by the runner.

These tests cover the host side (``drain``) and the app-side helpers
(``enqueue``, ``read_intent``, ``pending_summary``). See
docs/project/reviews/single-writer-design-2026-11-11.md.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.literary import queue_intents
from src.literary.models import BookRecord
from src.literary.queue import QueueStore


def _record(calibre_id: int, title: str) -> BookRecord:
    return BookRecord(
        calibre_id=calibre_id,
        title=title,
        author="Test Author",
        series="Test Series",
        series_index=float(calibre_id),
        languages=["en"],
        epub_path="",
    )


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "literary_queue.db"
    QueueStore(str(path)).close()
    return path


def _store(db: Path) -> QueueStore:
    return QueueStore(str(db))


def _intent_rows(db: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM queue_intents ORDER BY id"))
    finally:
        conn.close()


def test_enqueue_writes_a_spool_file_and_never_touches_the_database(db: Path):
    before = db.read_bytes()

    token = queue_intents.enqueue(db, "event", {"message": "hello", "book_id": None})

    assert db.read_bytes() == before
    spool = queue_intents.spool_dir(db)
    files = sorted(path.name for path in spool.iterdir())
    assert len(files) == 1 and files[0].endswith(f"-{token}.json")
    body = json.loads((spool / files[0]).read_text(encoding="utf-8"))
    assert body["kind"] == "event" and body["token"] == token
    assert queue_intents.read_intent(db, token)["state"] == "queued"


def test_enqueue_rejects_unknown_kinds(db: Path):
    with pytest.raises(ValueError):
        queue_intents.enqueue(db, "delete_everything", {})


def test_drain_migrates_an_existing_database_additively(db: Path):
    store = _store(db)
    store.add_book(_record(1, "Existing"), priority=5)
    store.close()

    first = queue_intents.drain(db)
    second = queue_intents.drain(db)

    assert first["pending"] == 0 and second["applied"] == 0
    conn = sqlite3.connect(db)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        titles = [row[0] for row in conn.execute("SELECT title FROM books")]
    finally:
        conn.close()
    assert "queue_intents" in tables
    assert titles == ["Existing"]
    assert [book.title for book in _store(db).list_books()] == ["Existing"]


def test_intents_apply_in_order_and_reorder_the_queue(db: Path):
    store = _store(db)
    first, second, third = (
        store.add_book(_record(index, f"Book {index}"), priority=priority)
        for index, priority in ((1, 300), (2, 200), (3, 100))
    )
    store.close()

    tokens = [
        queue_intents.enqueue(db, "move", {"book_id": third, "direction": "up"}),
        queue_intents.enqueue(db, "move", {"book_id": second, "direction": "up"}),
        queue_intents.enqueue(
            db, "update_model", {"book_id": first, "model": "m1", "provider": "ollama"}
        ),
    ]
    stats = queue_intents.drain(db)

    assert stats["applied"] == 3 and stats["refused"] == 0 and stats["pending"] == 0
    assert [book.id for book in _store(db).list_books(status="pending")] == [first, second, third]
    assert _store(db).get_book(first).model == "m1"
    for token in tokens:
        state = queue_intents.read_intent(db, token)
        assert state["state"] == "applied" and state["error"] == ""


def test_refusals_are_recorded_and_do_not_block_later_intents(db: Path):
    store = _store(db)
    book_id = store.add_book(_record(1, "Busy"))
    store.set_book_state(book_id, "preparing")
    store.set_book_state(book_id, "translating")
    store.close()

    refused = queue_intents.enqueue(db, "remove", {"book_id": book_id})
    later = queue_intents.enqueue(db, "event", {"message": "still applied", "book_id": book_id})
    queue_intents.drain(db)

    state = queue_intents.read_intent(db, refused)
    assert state["state"] == "applied"
    assert state["error_status"] == 409
    assert "pause the book" in state["error"]
    assert queue_intents.read_intent(db, later)["error"] == ""
    assert _store(db).get_book(book_id) is not None


def test_approve_applies_the_whole_transition_in_one_go(db: Path):
    store = _store(db)
    book_id = store.add_book(_record(1, "Review"))
    job_id = store.create_job(book_id)
    for state in ("preparing", "translating", "needs_review"):
        store.set_book_state(book_id, state)
        store.set_job_state(job_id, state)
    store.close()

    token = queue_intents.enqueue(db, "approve", {"book_id": book_id})
    queue_intents.drain(db)

    assert queue_intents.read_intent(db, token)["error"] == ""
    book = _store(db).get_book(book_id)
    assert book.status == "completed" and book.reviewed_at
    assert _store(db).latest_job(book_id)["state"] == "completed"


def test_remove_leaves_no_event_pointing_at_the_deleted_book(db: Path):
    store = _store(db)
    book_id = store.add_book(_record(1, "Gone"))
    store.close()

    queue_intents.enqueue(db, "remove", {"book_id": book_id})
    queue_intents.drain(db)

    conn = sqlite3.connect(db)
    try:
        dangling = conn.execute(
            "SELECT COUNT(*) FROM events e WHERE e.book_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM books b WHERE b.id = e.book_id)"
        ).fetchone()[0]
        removal = conn.execute(
            "SELECT book_id, message FROM events WHERE message LIKE 'removed from queue%'"
        ).fetchone()
    finally:
        conn.close()
    assert dangling == 0
    assert removal[0] is None and "Gone" in removal[1]


def test_retry_releases_a_stale_checkpoint_when_the_app_says_so(db: Path):
    store = _store(db)
    book_id = store.add_book(_record(1, "Paused"))
    job_id = store.create_job(book_id, total_chapters=10)
    store.attach_translation_id(job_id, "cli_stale")
    for state in ("preparing", "translating", "paused"):
        store.set_book_state(book_id, state)
    store.set_job_state(job_id, "paused")
    store.close()

    queue_intents.enqueue(
        db, "retry", {"book_id": book_id, "release_stale_checkpoint": True}
    )
    queue_intents.drain(db)

    store = _store(db)
    assert store.get_book(book_id).status == "pending"
    assert store.latest_job(book_id)["translation_id"] == ""
    store.close()


def test_add_reports_books_that_are_already_queued(db: Path):
    store = _store(db)
    store.add_book(_record(1, "Queued"))
    store.close()

    token = queue_intents.enqueue(
        db,
        "add",
        {
            "books": [
                {"calibre_id": 1, "title": "Queued", "languages": ["en"], "source_hash": "", "config_hash": "c"},
                {"calibre_id": 2, "title": "New", "languages": ["en"], "source_hash": "", "config_hash": "c"},
            ],
            "target_language": "pt-BR",
            "model": "",
            "provider": "",
        },
    )
    queue_intents.drain(db)

    result = queue_intents.read_intent(db, token)["result"]
    assert result["duplicates"] == [1]
    assert len(result["added"]) == 1
    assert sorted(book.calibre_id for book in _store(db).list_books()) == [1, 2]


def test_intents_wait_while_the_runner_is_stopped_and_resume_in_order(db: Path):
    tokens = [queue_intents.enqueue(db, "event", {"message": f"m{i}"}) for i in range(3)]

    assert [queue_intents.read_intent(db, token)["state"] for token in tokens] == ["queued"] * 3
    assert queue_intents.pending_summary(db)["pending"] == 3

    queue_intents.drain(db)

    assert queue_intents.pending_summary(db)["pending"] == 0
    conn = sqlite3.connect(db)
    try:
        messages = [row[0] for row in conn.execute(
            "SELECT message FROM events WHERE message LIKE 'm_' ORDER BY id"
        )]
    finally:
        conn.close()
    assert messages == ["m0", "m1", "m2"]


def test_drain_is_idempotent_when_a_spool_file_survives_a_crash(db: Path):
    token = queue_intents.enqueue(db, "event", {"message": "once"})
    spool = queue_intents.spool_dir(db)
    original = next(spool.glob(f"*-{token}.json")).read_text(encoding="utf-8")
    queue_intents.drain(db)

    # Simulate a crash after the ingest commit but before the spool unlink.
    (spool / f"00000000000000000001-{token}.json").write_text(original, encoding="utf-8")
    queue_intents.drain(db)

    rows = [row for row in _intent_rows(db) if row["token"] == token]
    assert len(rows) == 1
    assert list(spool.glob("*.json")) == []
    messages = [row[0] for row in sqlite3.connect(db).execute(
        "SELECT message FROM events WHERE message = 'once'"
    )]
    assert messages == ["once"]


def test_malformed_spool_files_are_refused_at_ingest(db: Path):
    spool = queue_intents.spool_dir(db)
    spool.mkdir(parents=True)
    (spool / "00000000000000000001-broken.json").write_text("not json", encoding="utf-8")

    stats = queue_intents.drain(db)

    rows = [row for row in _intent_rows(db) if row["kind"] == "malformed"]
    assert stats["pending"] == 0
    assert len(rows) == 1 and rows[0]["error_status"] == 400
    assert "malformed" in rows[0]["error"]


def test_a_held_write_lock_defers_the_batch_and_the_next_drain_applies_it(db: Path, monkeypatch):
    monkeypatch.setattr(queue_intents, "BUSY_TIMEOUT_MS", 200)
    token = queue_intents.enqueue(db, "event", {"message": "after the lock"})
    holder = sqlite3.connect(db, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        deferred = queue_intents.drain(db)
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert deferred["deferred"] is True
    assert queue_intents.read_intent(db, token)["state"] == "queued"

    queue_intents.drain(db)

    assert queue_intents.read_intent(db, token)["state"] == "applied"


def test_unknown_or_malformed_tokens_are_not_found(db: Path):
    assert queue_intents.read_intent(db, "f" * 32) is None
    assert queue_intents.read_intent(db, "../../etc/passwd") is None
