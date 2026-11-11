"""Tests for the supervisor's deterministic term fix and retry policy."""
from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

from .conftest import make_epub

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("auto_queue", ROOT / "scripts" / "auto_queue.py")
assert SPEC and SPEC.loader
auto_queue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto_queue)


def test_rewrite_epub_terms_replaces_whole_words_only(tmp_path: Path):
    epub = tmp_path / "book.epub"
    make_epub(
        epub,
        chapters=[
            "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
            "<p>A Chantry vigia. As Chantries ficam longe.</p>"
            "</body></html>",
            "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
            "<p>Nada aqui.</p></body></html>",
        ],
    )
    output = tmp_path / "fixed.epub"
    counts = auto_queue._rewrite_epub_terms(epub, {"chantry": "Chantria"}, output)

    assert counts == {"chantry": 1}
    assert output.exists()
    with zipfile.ZipFile(output) as archive:
        text = archive.read("OEBPS/ch1.xhtml").decode("utf-8")
        style = archive.read("OEBPS/style.css").decode("utf-8")
    assert "Chantria" in text
    assert "Chantries" in text
    assert "Chantry" not in text
    assert "Chantry" not in style


def test_rewrite_epub_terms_preserves_uppercase(tmp_path: Path):
    epub = tmp_path / "book.epub"
    make_epub(
        epub,
        chapters=[
            "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
            "<p>O SONO, ENTÃO, SEGUNDO O CHANTRY</p></body></html>",
            "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>Nada.</p></body></html>",
        ],
    )
    auto_queue._rewrite_epub_terms(epub, {"Chantry": "Chantria"})
    with zipfile.ZipFile(epub) as archive:
        text = archive.read("OEBPS/ch1.xhtml").decode("utf-8")
    assert "SEGUNDO O CHANTRIA" in text


def test_rewrite_epub_terms_in_place_keeps_other_entries(tmp_path: Path):
    epub = tmp_path / "book.epub"
    make_epub(epub)
    with zipfile.ZipFile(epub) as archive:
        before = set(archive.namelist())

    auto_queue._rewrite_epub_terms(epub, {"Chapter": "Capítulo"})

    with zipfile.ZipFile(epub) as archive:
        after = set(archive.namelist())
        text = archive.read("OEBPS/ch1.xhtml").decode("utf-8")
    assert before == after
    assert "Capítulo One" in text


def test_can_retry_requires_checkpoint_and_budget():
    book = {"id": 10, "title": "Howling Dark", "status": "failed"}
    job = {"id": 21, "translation_id": "cli_c00e8ea2", "error": "process died"}

    assert auto_queue._can_retry(book, job, {}, 0) is False
    assert auto_queue._can_retry(book, None, {}, 1) is False
    assert auto_queue._can_retry(book, {"id": 21}, {}, 1) is False
    assert auto_queue._can_retry(
        book, {**job, "error": "validation gate failed"}, {}, 1
    ) is False
    assert auto_queue._can_retry(
        book, {**job, "error": "paused by user from the queue UI"}, {}, 1
    ) is False
    assert auto_queue._can_retry(book, job, {}, 1) is True
    assert auto_queue._can_retry(book, job, {10: 1}, 1) is False
