"""Tests for the queue runner's path/model helpers."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.literary import queue_runner


def test_model_aliases_resolve_to_official_tags():
    assert queue_runner.resolve_model("hy-mt2-7b") == "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
    assert queue_runner.resolve_model("hy-mt2-7b-q6") == "hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K"
    assert queue_runner.resolve_model("custom:tag") == "custom:tag"


def test_output_name_sanitizes_windows_forbidden_characters():
    book = SimpleNamespace(title='A/B: "C"?')
    assert queue_runner.output_name(book) == "AB C (pt-BR).epub"


def test_library_path_is_kept_and_windows_path_is_mapped(tmp_path: Path, monkeypatch):
    inventory = tmp_path / "targets.json"
    inventory.write_text(
        json.dumps(
            {
                "books": [
                    {
                        "calibre_id": 42,
                        "calibre_path": "Author/Book (42)",
                        "epub_path": str(tmp_path / "Book - Author.epub"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "Book - Author.epub").write_bytes(b"fake")
    monkeypatch.setattr(queue_runner, "INVENTORY", inventory)

    library = SimpleNamespace(source_path="/library/Author/Book (42)/Book.epub", calibre_id=42)
    assert queue_runner.container_source(library) == library.source_path

    windows = SimpleNamespace(
        source_path=r"C:\Library\Author\Book (42)\Book - Author.epub",
        calibre_id=42,
    )
    assert queue_runner.container_source(windows) == "/library/Author/Book (42)/Book - Author.epub"


def test_host_source_falls_back_to_inventory_epub(tmp_path: Path, monkeypatch):
    epub = tmp_path / "Book - Author.epub"
    epub.write_bytes(b"fake")
    inventory = tmp_path / "targets.json"
    inventory.write_text(
        json.dumps(
            {
                "books": [
                    {
                        "calibre_id": 42,
                        "calibre_path": "Author/Book (42)",
                        "epub_path": str(epub),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(queue_runner, "INVENTORY", inventory)
    book = SimpleNamespace(source_path="/library/missing.epub", calibre_id=42)
    assert queue_runner.host_source(book) == epub
import sqlite3
from pathlib import Path

def test_find_translation_id_since_skips_old_jobs(tmp_path: Path, monkeypatch):
    db = tmp_path / "jobs.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE translation_jobs (translation_id TEXT, config TEXT, created_at TEXT)")
    con.execute(
        "INSERT INTO translation_jobs VALUES (?, ?, ?)",
        ("cli_old", '{"input_file_path":"/library/Ship of Magic.epub"}', "2026-11-08 18:20:00"),
    )
    con.execute(
        "INSERT INTO translation_jobs VALUES (?, ?, ?)",
        ("cli_new", '{"input_file_path":"/library/Ship of Magic.epub"}', "2026-11-08 18:21:00"),
    )
    con.commit(); con.close()
    monkeypatch.setattr(queue_runner, "CHECKPOINT_DB", db)
    assert queue_runner._find_translation_id("Ship of Magic") == "cli_new"
    assert queue_runner._find_translation_id("Ship of Magic", "2026-11-08 18:21:00") == "cli_new"
    assert queue_runner._find_translation_id("Ship of Magic", "2026-11-08 18:22:00") is None

def test_is_sun_eater_detects_author_and_series():
    from src.literary.queue_runner import _is_sun_eater

    class Book:
        author = "Christopher Ruocchio"
        series = "The Sun Eater"

    class Other:
        author = "Robin Hobb"
        series = "The Liveship Traders"

    assert _is_sun_eater(Book())
    assert not _is_sun_eater(Other())
