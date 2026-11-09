"""Tests for the batch reader-repair command."""
from __future__ import annotations

import json
from pathlib import Path

from src.literary.models import BookRecord
from src.literary.polish import polish_completed_books
from src.literary.queue import QueueStore
from src.literary.queue_insights import quality_sidecar_path

from .conftest import make_epub


def _completed_book(store: QueueStore, tmp_path: Path, *, title: str, author: str) -> int:
    epub = tmp_path / f"{title}.epub"
    make_epub(epub, title=title)
    book_id = store.add_book(
        BookRecord(
            calibre_id=abs(hash(title)) % 100000,
            title=title,
            author=author,
            series="The Sun Eater" if "Ruocchio" in author else "The Liveship Traders",
            series_index=2.0,
            languages=["en"],
            epub_path=str(epub),
        )
    )
    for state in ("preparing", "translating", "reviewing", "validating", "completed"):
        store.set_book_state(book_id, state)
    store.mark_reviewed(book_id, "test review")
    return book_id


def test_polish_completed_sun_eater_book_and_skip_on_second_run(tmp_path: Path):
    db = tmp_path / "queue.db"
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    store = QueueStore(str(db))
    book_id = _completed_book(
        store, tmp_path, title="Howling Dark", author="Christopher Ruocchio"
    )
    store.close()
    make_epub(outputs / "Howling Dark (pt-BR).refined.epub", title="Howling Dark")

    first = polish_completed_books(
        str(db), outputs, book_id=book_id, run_epubcheck=False, kindle_out=""
    )

    assert first["polished"] == 1
    assert first["results"][0]["status"] == "polished"
    artifact = outputs / "Howling Dark (pt-BR).refined.epub"
    sidecar = quality_sidecar_path(artifact)
    assert sidecar.is_file()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["reader_repair"]["accepted"] is True
    assert "quality_flags" in payload

    second = polish_completed_books(
        str(db), outputs, book_id=book_id, run_epubcheck=False, kindle_out=""
    )
    assert second["skipped"] == 1
    assert second["results"][0]["reason"] == "already polished"


def test_polish_skips_non_sun_eater_books(tmp_path: Path):
    db = tmp_path / "queue.db"
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    store = QueueStore(str(db))
    _completed_book(store, tmp_path, title="Ship of Magic", author="Robin Hobb")
    store.close()

    result = polish_completed_books(str(db), outputs, run_epubcheck=False, kindle_out="")

    assert result["books"] == 1
    assert result["skipped"] == 1
    assert result["results"][0]["reason"] == "not Sun Eater"
