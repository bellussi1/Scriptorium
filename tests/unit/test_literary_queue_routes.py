"""Tests for the literary queue API (snapshot, library, add, reorder)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from flask import Flask

from src.api.blueprints.literary_queue_routes import (
    build_library_inventory,
    build_queue_snapshot,
    create_literary_queue_blueprint,
)
from src.literary.models import BookRecord
from src.literary.queue import QueueStore


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
            priority INTEGER DEFAULT 0,
            reviewed_at TEXT DEFAULT ''
        );
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            book_id INTEGER,
            state TEXT,
            translation_id TEXT,
            current_chapter INTEGER,
            total_chapters INTEGER,
            error TEXT,
            created_at TEXT,
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
        "'The Sun Eater', 2.0, 'translating', 264961, 'hy-mt2', 'ollama', 0, '')"
    )
    conn.execute(
        "INSERT INTO books VALUES (2, 101, 'Demon in White', 'Christopher Ruocchio', "
        "'The Sun Eater', 3.0, 'pending', 295868, 'hy-mt2', 'ollama', 0, '')"
    )
    conn.execute(
        "INSERT INTO jobs VALUES (1, 1, 'translating', 'cli_test', 10, 100, '', "
        "'2026-11-08T00:00:00+00:00', '2026-11-08T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO events (level, message, created_at) VALUES "
        "('info', 'full-book translation started: cli_test', '2026-11-08T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


def _inventory(path: Path, rows: list[dict]) -> Path:
    path.write_text(json.dumps({"books": rows}, ensure_ascii=False), encoding="utf-8")
    return path


def _inventory_row(calibre_id: int, title: str, language: str = "en") -> dict:
    return {
        "calibre_id": calibre_id,
        "title": title,
        "author": "Test Author",
        "series": "Test Series",
        "series_index": 1.0,
        "languages": [language],
        "calibre_path": f"Test Author/{title} ({calibre_id})",
        "epub_path": f"C:\\Library\\Test Author\\{title} ({calibre_id})\\{title}.epub",
        "word_count": 1000 + calibre_id,
    }


def _client(tmp_path: Path, monkeypatch, *, rows: list[dict]) -> Flask:
    monkeypatch.setenv("LITERARY_QUEUE_DB", str(tmp_path / "queue.db"))
    monkeypatch.setenv("LITERARY_INVENTORY", str(_inventory(tmp_path / "inventory.json", rows)))
    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())
    return app


def _seed_book(tmp_path: Path, calibre_id: int, title: str) -> int:
    store = QueueStore(str(tmp_path / "queue.db"))
    epub = tmp_path / f"{calibre_id}.epub"
    epub.write_bytes(b"fake epub")
    book_id = store.add_book(
        BookRecord(
            calibre_id=calibre_id,
            title=title,
            author="Test Author",
            series="Test Series",
            series_index=1.0,
            languages=["en"],
            epub_path=str(epub),
        )
    )
    store.close()
    return book_id


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
    assert first["state"] == "translating"
    assert first["live"] is True
    assert first["job_created_at"] == "2026-11-08T00:00:00+00:00"
    assert "source_path" not in first
    assert snapshot["events"][0]["message"].startswith("full-book translation")
    second = snapshot["books"][1]
    assert second["state"] == "pending"
    assert second["position"] == 1
    assert second["is_next"] is True


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


def test_library_lists_only_unqued_english_books(tmp_path: Path, monkeypatch):
    rows = [
        _inventory_row(1, "English One"),
        _inventory_row(2, "Portuguese One", language="por"),
        _inventory_row(3, "Already Queued"),
    ]
    inventory = _inventory(tmp_path / "inventory.json", rows)
    monkeypatch.setenv("LITERARY_INVENTORY", str(inventory))
    _seed_book(tmp_path, 3, "Already Queued")

    payload = build_library_inventory(tmp_path / "queue.db")

    assert payload["status"] == "ok"
    assert payload["count"] == 1
    assert payload["books"][0]["calibre_id"] == 1
    assert payload["books"][0]["title"] == "English One"
    assert payload["books"][0]["word_count"] == 1001
    assert inventory.exists()


def test_library_returns_503_without_inventory(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LITERARY_QUEUE_DB", str(tmp_path / "queue.db"))
    monkeypatch.setenv("LITERARY_INVENTORY", str(tmp_path / "missing.json"))
    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())

    response = app.test_client().get("/api/literary/library")

    assert response.status_code == 503
    assert "inventory" in response.get_json()["error"].lower()


def test_add_books_enqueues_and_skips_duplicates(tmp_path: Path, monkeypatch):
    rows = [_inventory_row(10, "First"), _inventory_row(11, "Second")]
    app = _client(tmp_path, monkeypatch, rows=rows)
    client = app.test_client()

    response = client.post(
        "/api/literary/queue/books", json={"calibre_ids": [10, 99, 11]}
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert len(payload["added"]) == 2
    assert payload["not_found"] == [99]
    assert payload["duplicates"] == []
    assert payload["summary"]["books"] == 2
    assert [book["title"] for book in payload["books"]] == ["First", "Second"]
    assert payload["books"][0]["word_count"] == 1010
    stored = QueueStore(str(tmp_path / "queue.db"))
    assert stored.list_books()[0].source_path.startswith("/library/Test Author/First (10)/")
    stored.close()

    again = client.post("/api/literary/queue/books", json={"calibre_ids": [10, 11]})
    assert again.status_code == 200
    assert again.get_json()["added"] == []
    assert again.get_json()["duplicates"] == [10, 11]


def test_add_books_rejects_invalid_payloads(tmp_path: Path, monkeypatch):
    rows = [_inventory_row(10, "First")]
    client = _client(tmp_path, monkeypatch, rows=rows).test_client()

    for body in ({}, {"calibre_ids": []}, {"calibre_ids": ["nope"]}, {"calibre_ids": [-1]}):
        response = client.post("/api/literary/queue/books", json=body)
        assert response.status_code == 400


def test_add_books_rejects_non_english_sources(tmp_path: Path, monkeypatch):
    rows = [_inventory_row(10, "First"), _inventory_row(20, "Traduzido", language="por")]
    client = _client(tmp_path, monkeypatch, rows=rows).test_client()

    response = client.post("/api/literary/queue/books", json={"calibre_ids": [20]})

    assert response.status_code == 400
    assert "English" in response.get_json()["error"]
    assert build_queue_snapshot(tmp_path / "queue.db")["summary"]["books"] == 0


def test_move_reorders_pending_books_and_blocks_edges(tmp_path: Path, monkeypatch):
    rows = [
        _inventory_row(10, "First"),
        _inventory_row(11, "Second"),
        _inventory_row(12, "Third"),
    ]
    client = _client(tmp_path, monkeypatch, rows=rows).test_client()
    client.post("/api/literary/queue/books", json={"calibre_ids": [10, 11, 12]})
    store = QueueStore(str(tmp_path / "queue.db"))
    ids = [book.id for book in store.list_books()]
    store.close()

    response = client.post(
        f"/api/literary/queue/books/{ids[1]}/move", json={"direction": "up"}
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert [book["title"] for book in payload["books"]] == ["Second", "First", "Third"]
    assert payload["moved"] == {"book_id": ids[1], "direction": "up"}

    edge = client.post(
        f"/api/literary/queue/books/{ids[1]}/move", json={"direction": "up"}
    )
    assert edge.status_code == 409

    missing = client.post(
        "/api/literary/queue/books/9999/move", json={"direction": "down"}
    )
    assert missing.status_code == 404

    bad_direction = client.post(
        f"/api/literary/queue/books/{ids[0]}/move", json={"direction": "left"}
    )
    assert bad_direction.status_code == 400


def test_move_rejects_non_pending_books(tmp_path: Path, monkeypatch):
    rows = [_inventory_row(10, "First"), _inventory_row(11, "Second")]
    client = _client(tmp_path, monkeypatch, rows=rows).test_client()
    client.post("/api/literary/queue/books", json={"calibre_ids": [10, 11]})
    store = QueueStore(str(tmp_path / "queue.db"))
    book = store.list_books()[0]
    store.set_book_state(book.id, "preparing")
    store.close()

    response = client.post(
        f"/api/literary/queue/books/{book.id}/move", json={"direction": "down"}
    )

    assert response.status_code == 409


def test_remove_pending_book_deletes_entry_and_keeps_an_event(tmp_path: Path, monkeypatch):
    rows = [_inventory_row(10, "First"), _inventory_row(11, "Second")]
    client = _client(tmp_path, monkeypatch, rows=rows).test_client()
    client.post("/api/literary/queue/books", json={"calibre_ids": [10, 11]})
    store = QueueStore(str(tmp_path / "queue.db"))
    book = next(item for item in store.list_books() if item.calibre_id == 10)
    store.close()

    response = client.delete(f"/api/literary/queue/books/{book.id}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["removed"]["book_id"] == book.id
    assert [item["title"] for item in payload["books"]] == ["Second"]
    assert any("removed from queue: First" in event["message"] for event in payload["events"])
    store = QueueStore(str(tmp_path / "queue.db"))
    assert store.get_book(book.id) is None
    assert store.latest_job(book.id) is None
    store.close()


def test_remove_rejects_active_book(tmp_path: Path, monkeypatch):
    rows = [_inventory_row(10, "First")]
    client = _client(tmp_path, monkeypatch, rows=rows).test_client()
    client.post("/api/literary/queue/books", json={"calibre_ids": [10]})
    store = QueueStore(str(tmp_path / "queue.db"))
    book = store.list_books()[0]
    store.set_book_state(book.id, "preparing", "test")
    store.close()

    response = client.delete(f"/api/literary/queue/books/{book.id}")

    assert response.status_code == 409
    assert "pause" in response.get_json()["error"]
    store = QueueStore(str(tmp_path / "queue.db"))
    assert store.get_book(book.id) is not None
    store.close()


def test_remove_missing_book_returns_404(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch, rows=[]).test_client()
    response = client.delete("/api/literary/queue/books/999")
    assert response.status_code == 404


def test_snapshot_puts_active_books_first(tmp_path: Path, monkeypatch):
    rows = [
        _inventory_row(10, "First"),
        _inventory_row(11, "Second"),
        _inventory_row(12, "Third"),
    ]
    client = _client(tmp_path, monkeypatch, rows=rows).test_client()
    client.post("/api/literary/queue/books", json={"calibre_ids": [10, 11, 12]})
    store = QueueStore(str(tmp_path / "queue.db"))
    pending = store.list_books()
    store.set_book_state(pending[-1].id, "preparing")
    store.close()

    payload = client.get("/api/literary/queue").get_json()

    assert payload["books"][0]["title"] == "Third"
    assert payload["books"][0]["job_state"] is None
    assert payload["books"][0]["status"] == "preparing"

def test_patch_updates_model_only_for_pending_books(tmp_path: Path, monkeypatch):
    rows = [_inventory_row(10, "First"), _inventory_row(11, "Second")]
    client = _client(tmp_path, monkeypatch, rows=rows).test_client()
    client.post("/api/literary/queue/books", json={"calibre_ids": [10, 11]})
    store = QueueStore(str(tmp_path / "queue.db"))
    pending = store.list_books()
    store.close()
    first_id, second_id = pending[0].id, pending[1].id

    response = client.patch(
        f"/api/literary/queue/books/{first_id}",
        json={"model": "hf.co/tencent/Hy-MT2-7B-GGUF:Q5_K_M", "provider": "ollama"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["updated"]["model"] == "hf.co/tencent/Hy-MT2-7B-GGUF:Q5_K_M"
    assert payload["books"][0]["model"] == "hf.co/tencent/Hy-MT2-7B-GGUF:Q5_K_M"
    assert payload["books"][0]["provider"] == "ollama"

    store = QueueStore(str(tmp_path / "queue.db"))
    store.set_book_state(second_id, "preparing")
    store.close()
    blocked = client.patch(
        f"/api/literary/queue/books/{second_id}",
        json={"model": "other", "provider": "ollama"},
    )
    assert blocked.status_code == 409

    assert client.patch(
        f"/api/literary/queue/books/{first_id}", json={"model": "  ", "provider": "ollama"}
    ).status_code == 400
    assert client.patch(
        "/api/literary/queue/books/9999", json={"model": "other", "provider": "ollama"}
    ).status_code == 404

def test_snapshot_exposes_best_download_artifact(tmp_path: Path, monkeypatch):
    db = tmp_path / "queue.db"
    _queue_db(db)
    outputs = tmp_path / "translated_files"
    outputs.mkdir()
    (outputs / "Howling Dark (pt-BR).epub").write_bytes(b"draft")
    (outputs / "Howling Dark (pt-BR) - fixed.epub").write_bytes(b"fixed")
    (outputs / "Howling Dark (pt-BR).refined.epub").write_bytes(b"refined")
    monkeypatch.setenv("LITERARY_OUTPUT_DIR", str(outputs))

    snapshot = build_queue_snapshot(db)
    artifact = snapshot["books"][0]["artifact"]
    assert artifact["kind"] == "refined"
    assert artifact["filename"] == "Howling Dark (pt-BR).refined.epub"
    assert artifact["download_url"].endswith("/1/download")


def test_download_route_returns_the_best_epub(tmp_path: Path, monkeypatch):
    db = tmp_path / "queue.db"
    _queue_db(db)
    outputs = tmp_path / "translated_files"
    outputs.mkdir()
    (outputs / "Howling Dark (pt-BR).refined.epub").write_bytes(b"refined-bytes")
    monkeypatch.setenv("LITERARY_QUEUE_DB", str(db))
    monkeypatch.setenv("LITERARY_OUTPUT_DIR", str(outputs))
    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())
    client = app.test_client()

    response = client.get("/api/literary/queue/books/1/download")
    assert response.status_code == 200
    assert response.data == b"refined-bytes"
    assert "Howling Dark (pt-BR).refined.epub" in response.headers["Content-Disposition"]

    missing = client.get("/api/literary/queue/books/2/download")
    assert missing.status_code == 404

def test_log_route_returns_the_tail(tmp_path: Path, monkeypatch):
    db = tmp_path / "queue.db"
    _queue_db(db)
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    (run_dir / "howling-dark.log").write_text("first\nsecond\nthird", encoding="utf-8")
    monkeypatch.setenv("LITERARY_QUEUE_DB", str(db))
    monkeypatch.setenv("LITERARY_RUN_DIR", str(run_dir))

    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())
    response = app.test_client().get("/api/literary/queue/books/1/log?lines=2")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["lines"] == ["second", "third"]


def test_quality_route_reads_the_best_artifact(tmp_path: Path, monkeypatch):
    from tests.literary.conftest import make_epub

    db = tmp_path / "queue.db"
    _queue_db(db)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    make_epub(outputs / "Howling Dark (pt-BR).refined.epub", title="Howling Dark")
    monkeypatch.setenv("LITERARY_QUEUE_DB", str(db))
    monkeypatch.setenv("LITERARY_OUTPUT_DIR", str(outputs))

    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())
    response = app.test_client().get("/api/literary/queue/books/1/quality")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["artifact"]["kind"] == "refined"
    assert payload["metrics"]["words"] > 0
    assert payload["book"]["title"] == "Howling Dark"


def test_kindle_zip_route_packages_the_library(tmp_path: Path, monkeypatch):
    import io
    import zipfile

    kindle = tmp_path / "kindle"
    kindle.mkdir()
    (kindle / "book.epub").write_bytes(b"epub")
    monkeypatch.setenv("LITERARY_KINDLE_DIR", str(kindle))

    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())
    response = app.test_client().get("/api/literary/queue/kindle.zip")

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert "book.epub" in archive.namelist()


def test_approve_route_completes_a_needs_review_book(tmp_path: Path, monkeypatch):
    app = _client(tmp_path, monkeypatch, rows=[])
    book_id = _seed_book(tmp_path, 20, "Needs Review")
    store = QueueStore(str(tmp_path / "queue.db"))
    job_id = store.create_job(book_id)
    for state in ("preparing", "translating", "needs_review"):
        store.set_book_state(book_id, state)
        store.set_job_state(job_id, state)
    store.close()

    response = app.test_client().post(f"/api/literary/queue/books/{book_id}/approve")

    assert response.status_code == 200
    snapshot = response.get_json()
    book = next(item for item in snapshot["books"] if item["id"] == book_id)
    assert book["state"] == "completed"


def test_retry_route_returns_a_failed_book_to_pending(tmp_path: Path, monkeypatch):
    app = _client(tmp_path, monkeypatch, rows=[])
    book_id = _seed_book(tmp_path, 21, "Failed Book")
    store = QueueStore(str(tmp_path / "queue.db"))
    job_id = store.create_job(book_id)
    store.set_book_state(book_id, "failed")
    store.set_job_state(job_id, "failed")
    store.close()

    response = app.test_client().post(f"/api/literary/queue/books/{book_id}/retry")

    assert response.status_code == 200
    snapshot = response.get_json()
    book = next(item for item in snapshot["books"] if item["id"] == book_id)
    assert book["state"] == "pending"
    assert book["position"] == 1

def test_add_books_rejects_a_non_ptbr_target(tmp_path: Path, monkeypatch):
    rows = [_inventory_row(30, "English One")]
    app = _client(tmp_path, monkeypatch, rows=rows)

    response = app.test_client().post(
        "/api/literary/queue/books",
        json={"calibre_ids": [30], "target_language": "French"},
    )

    assert response.status_code == 400
    assert "Brazilian Portuguese" in response.get_json()["error"]


def test_control_route_round_trips_a_pause_request(tmp_path: Path, monkeypatch):
    app = _client(tmp_path, monkeypatch, rows=[])
    client = app.test_client()

    initial = client.get("/api/literary/queue/control")
    assert initial.status_code == 200
    assert initial.get_json()["pause_after_book"] is False

    requested = client.post(
        "/api/literary/queue/control", json={"pause_after_book": True}
    )
    assert requested.status_code == 200
    payload = requested.get_json()
    assert payload["pause_after_book"] is True
    assert payload["requested_at"]

    current = client.get("/api/literary/queue/control").get_json()
    assert current["pause_after_book"] is True
    assert (tmp_path / "queue.control.json").is_file()

    cleared = client.post(
        "/api/literary/queue/control", json={"pause_after_book": False}
    )
    assert cleared.status_code == 200
    assert cleared.get_json()["pause_after_book"] is False


def test_control_route_rejects_a_non_boolean_value(tmp_path: Path, monkeypatch):
    app = _client(tmp_path, monkeypatch, rows=[])

    response = app.test_client().post(
        "/api/literary/queue/control", json={"pause_after_book": "yes"}
    )

    assert response.status_code == 400
    assert "boolean" in response.get_json()["error"]


def test_control_route_round_trips_pause_now(tmp_path: Path, monkeypatch):
    app = _client(tmp_path, monkeypatch, rows=[])
    client = app.test_client()

    requested = client.post(
        "/api/literary/queue/control", json={"pause_now": True}
    )
    assert requested.status_code == 200
    payload = requested.get_json()
    assert payload["pause_now"] is True
    assert payload["pause_now_requested_at"]

    current = client.get("/api/literary/queue/control").get_json()
    assert current["pause_now"] is True

    cleared = client.post(
        "/api/literary/queue/control", json={"pause_now": False}
    )
    assert cleared.status_code == 200
    assert cleared.get_json()["pause_now"] is False


def test_control_route_requires_at_least_one_flag(tmp_path: Path, monkeypatch):
    app = _client(tmp_path, monkeypatch, rows=[])

    response = app.test_client().post("/api/literary/queue/control", json={})

    assert response.status_code == 400
    assert "pause_after_book or pause_now" in response.get_json()["error"]


def test_approve_route_accepts_an_unreviewed_completed_book(tmp_path: Path, monkeypatch):
    app = _client(tmp_path, monkeypatch, rows=[])
    book_id = _seed_book(tmp_path, 22, "Auto Completed")
    store = QueueStore(str(tmp_path / "queue.db"))
    job_id = store.create_job(book_id)
    for state in ("preparing", "translating", "validating", "completed"):
        store.set_book_state(book_id, state)
        store.set_job_state(job_id, state)
    store.close()

    before = app.test_client().get("/api/literary/queue").get_json()
    book = next(item for item in before["books"] if item["id"] == book_id)
    assert book["state"] == "needs_review"
    assert book["unreviewed_completion"] is True
    assert book["reviewed"] is False

    response = app.test_client().post(f"/api/literary/queue/books/{book_id}/approve")

    assert response.status_code == 200
    after = response.get_json()
    book = next(item for item in after["books"] if item["id"] == book_id)
    assert book["state"] == "completed"
    assert book["reviewed"] is True
    assert book["reviewed_at"]


def _runner_behind(monkeypatch) -> None:
    """The host runner has not applied anything yet: the route must answer 202."""
    from src.api.blueprints import literary_queue_routes as routes

    monkeypatch.setattr(routes, "_await_intent", lambda db_path, token: None)


def test_mutations_answer_202_and_the_intent_is_readable_until_applied(tmp_path: Path, monkeypatch):
    from src.literary import queue_intents

    app = _client(tmp_path, monkeypatch, rows=[])
    _seed_book(tmp_path, 29, "Head Of Queue")
    book_id = _seed_book(tmp_path, 30, "Queued Later")
    db = tmp_path / "queue.db"
    _runner_behind(monkeypatch)
    client = app.test_client()

    response = client.post(f"/api/literary/queue/books/{book_id}/move", json={"direction": "up"})

    assert response.status_code == 202
    accepted = response.get_json()
    token = accepted["intent"]["token"]
    assert accepted["intent"]["state"] == "queued"
    assert accepted["intent"]["kind"] == "move"
    assert accepted["intents"]["pending"] == 1
    assert client.get(f"/api/literary/queue/intents/{token}").get_json()["state"] == "queued"

    queue_intents.drain(db)

    applied = client.get(f"/api/literary/queue/intents/{token}").get_json()
    assert applied["state"] == "applied" and applied["error"] == ""
    assert applied["result"]["moved"] == {"book_id": book_id, "direction": "up"}


def test_the_app_routes_never_write_the_queue_database(tmp_path: Path, monkeypatch):
    app = _client(tmp_path, monkeypatch, rows=[])
    first = _seed_book(tmp_path, 31, "First")
    second = _seed_book(tmp_path, 32, "Second")
    db = tmp_path / "queue.db"
    _runner_behind(monkeypatch)
    before = db.read_bytes()
    client = app.test_client()

    assert client.post(f"/api/literary/queue/books/{first}/move", json={"direction": "down"}).status_code == 202
    client.post(f"/api/literary/queue/books/{second}/approve")  # any status: no write
    assert client.patch(
        f"/api/literary/queue/books/{first}", json={"model": "m", "provider": "ollama"}
    ).status_code == 202
    assert client.delete(f"/api/literary/queue/books/{second}").status_code == 202
    assert client.post("/api/literary/queue/run", json={"mode": "next"}).status_code == 202

    assert db.read_bytes() == before


def test_intent_route_returns_404_for_unknown_tokens(tmp_path: Path, monkeypatch):
    app = _client(tmp_path, monkeypatch, rows=[])
    client = app.test_client()

    assert client.get("/api/literary/queue/intents/" + "a" * 32).status_code == 404
    assert client.get("/api/literary/queue/intents/not-a-token").status_code == 404
