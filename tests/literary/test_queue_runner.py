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
