"""Tests for the Kindle-ready library builder."""
from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

from src.literary.kindle import (
    author_sort,
    build_kindle_library,
    index_label,
    tags_for,
)
from src.literary.models import BookRecord
from src.literary.queue import QueueStore

from .conftest import make_epub


def test_series_labels_and_sorting():
    assert index_label(1) == "01"
    assert index_label(1.5) == "01.5"
    assert index_label(None) == "00"
    assert author_sort("Christopher Ruocchio") == "Ruocchio, Christopher"
    assert author_sort("Robin Hobb") == "Hobb, Robin"


def test_tags_include_series_and_language():
    hobb = tags_for(SimpleNamespace(author="Robin Hobb", series="The Liveship Traders"))
    assert "Fantasy" in hobb
    assert "The Liveship Traders" in hobb
    assert "Brazilian Portuguese" in hobb
    assert "Machine Translation" in hobb

    ruocchio = tags_for(SimpleNamespace(author="Christopher Ruocchio", series="The Sun Eater"))
    assert "Science Fiction" in ruocchio
    assert "Space Opera" in ruocchio


def test_build_kindle_library_copies_and_standardizes(tmp_path: Path):
    db = tmp_path / "queue.db"
    store = QueueStore(str(db))
    source = make_epub(tmp_path / "source.epub", title="Test Book")
    book_id = store.add_book(
        BookRecord(
            calibre_id=42,
            title="Test Book",
            author="Test Author",
            series="Test Series",
            series_index=2.0,
            languages=["en"],
            epub_path=str(source),
        )
    )
    for state in ("preparing", "translating", "validating", "completed"):
        store.set_book_state(book_id, state)
    store.close()

    outputs = tmp_path / "translated_files"
    outputs.mkdir()
    make_epub(outputs / "Test Book (pt-BR).refined.epub", title="Livro de Teste")
    root = tmp_path / "kindle"

    result = build_kindle_library(
        db_path=str(db),
        outputs_dir=str(outputs),
        output_root=str(root),
    )

    assert result["books"] == 1
    destination = root / "Test Author" / "Test Series" / "02 - Test Book (pt-BR).epub"
    assert destination.exists()
    with zipfile.ZipFile(destination) as archive:
        opf_path = next(name for name in archive.namelist() if name.endswith(".opf"))
        opf = archive.read(opf_path).decode("utf-8")
    assert "Livro de Teste" in opf
    assert 'name="calibre:series"' in opf
    assert "Test Series" in opf
    assert "Science Fiction" not in opf
    assert "Brazilian Portuguese" in opf
    assert "Machine Translation" in opf
    assert "TranslateBook with LLM (TBL)" in opf
    assert (root / "manifest.csv").exists()
    assert (root / "README.md").exists()
