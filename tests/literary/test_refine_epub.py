"""Tests for source-aware EPUB refinement."""
from __future__ import annotations

import zipfile
from pathlib import Path

from src.literary.refine_epub import (
    apply_paragraph_replacements,
    extract_paragraphs,
    refine_epub,
)

from .conftest import make_epub


SOURCE_CHAPTERS = [
    "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>One</h1>"
    "<p>I walked two miles and convinced myself that it was true.</p>"
    "<p>The second source paragraph has enough words to pass the length guard.</p>"
    "</body></html>",
    "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Two</h1>"
    "<p>The third source paragraph is quiet and deliberately short.</p>"
    "<p>The fourth source paragraph closes the chapter without any incident.</p>"
    "</body></html>",
]

DRAFT_CHAPTERS = [
    "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Um</h1>"
    "<p>Andei três milhas e Convinci-me de que era verdade.</p>"
    "<p>O segundo parágrafo traduzido tem palavras suficientes para o guarda.</p>"
    "</body></html>",
    "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Dois</h1>"
    "<p>O terceiro parágrafo traduzido é quieto e deliberadamente curto.</p>"
    "<p>O quarto parágrafo traduzido fecha o capítulo sem nenhum incidente.</p>"
    "</body></html>",
]


def _fake_generate(messages):
    user = messages[-1]["content"]
    if "três milhas" in user:
        return "Andei duas milhas e convenci-me de que era verdade."
    return "O segundo parágrafo traduzido tem palavras suficientes para o guarda."


def _chapter_text(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8")


def test_extract_paragraphs_marks_inline_markup():
    html = (
        "<body><p>Plain paragraph.</p>"
        "<p>With <em>italic</em> text.</p><h1>Heading</h1></body>"
    )
    paragraphs = extract_paragraphs(html)
    assert len(paragraphs) == 2
    assert paragraphs[0].has_inline_markup is False
    assert paragraphs[1].has_inline_markup is True


def test_apply_paragraph_replacements_preserves_markup():
    html = "<p>First wrong.</p><p>Second stays.</p>"
    paragraphs = extract_paragraphs(html)
    result = apply_paragraph_replacements(html, paragraphs, {0: "First fixed."})
    assert result == "<p>First fixed.</p><p>Second stays.</p>"


def test_refine_epub_applies_accepted_replacement(tmp_path: Path):
    source = make_epub(tmp_path / "source.epub", chapters=SOURCE_CHAPTERS)
    target = make_epub(tmp_path / "draft.epub", chapters=DRAFT_CHAPTERS)
    output = tmp_path / "refined.epub"

    report = refine_epub(
        str(source),
        str(target),
        str(output),
        model="test-model",
        generate=_fake_generate,
        limit=1,
    )

    assert report["accepted"] >= 1
    assert report["documents_refined"] >= 1
    chapter = _chapter_text(output, "OEBPS/ch1.xhtml")
    assert "duas milhas" in chapter
    assert "convenci-me" in chapter
    # The second paragraph was not flagged and must remain byte-for-byte same text.
    assert "O segundo parágrafo traduzido" in chapter


def test_refine_epub_skips_inline_markup(tmp_path: Path):
    source = make_epub(tmp_path / "source.epub", chapters=SOURCE_CHAPTERS)
    draft = [
        "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Um</h1>"
        "<p>Andei <em>três</em> milhas e Convinci-me de que era verdade.</p>"
        "<p>O segundo parágrafo traduzido tem palavras suficientes para o guarda.</p>"
        "</body></html>",
    ] + DRAFT_CHAPTERS[1:]
    target = make_epub(tmp_path / "draft.epub", chapters=draft)
    output = tmp_path / "refined.epub"

    report = refine_epub(
        str(source),
        str(target),
        str(output),
        model="test-model",
        generate=_fake_generate,
    )

    assert report["paragraphs_inline_markup_skipped"] >= 1
    chapter = _chapter_text(output, "OEBPS/ch1.xhtml")
    assert "<em>três</em>" in chapter
    assert "duas milhas" not in chapter


def test_refine_epub_skips_chapter_with_different_paragraph_count(tmp_path: Path):
    source = make_epub(tmp_path / "source.epub", chapters=SOURCE_CHAPTERS)
    draft = [
        "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Um</h1>"
        "<p>Só um parágrafo neste capítulo.</p>"
        "</body></html>",
    ] + DRAFT_CHAPTERS[1:]
    target = make_epub(tmp_path / "draft.epub", chapters=draft)
    output = tmp_path / "refined.epub"

    report = refine_epub(
        str(source),
        str(target),
        str(output),
        model="test-model",
        generate=_fake_generate,
    )

    assert any(item["reason"] == "paragraph_count_mismatch" for item in report["documents_skipped"])
    assert report["accepted"] == 0


def test_refine_epub_dry_run_flags_without_calling_model(tmp_path: Path):
    source = make_epub(tmp_path / "source.epub", chapters=SOURCE_CHAPTERS)
    target = make_epub(tmp_path / "draft.epub", chapters=DRAFT_CHAPTERS)
    output = tmp_path / "refined.epub"
    called = {"count": 0}

    def _generate(messages):
        called["count"] += 1
        return _fake_generate(messages)

    report = refine_epub(
        str(source),
        str(target),
        str(output),
        model="test-model",
        generate=_generate,
        dry_run=True,
    )

    assert called["count"] == 0
    assert report["flagged"] >= 1
    assert report["accepted"] == 0
    assert output.exists()


def test_limit_stops_after_the_requested_number_of_segments(tmp_path: Path):
    source_chapters = [
        "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
        "<p>I walked two miles and convinced myself that it was true.</p>"
        "<p>A second plain paragraph with enough words for the length guard.</p>"
        "</body></html>",
        "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
        "<p>I walked three miles and convinced myself that it was true.</p>"
        "<p>A fourth plain paragraph with enough words for the length guard.</p>"
        "</body></html>",
    ]
    draft_chapters = [
        "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
        "<p>Andei quatro milhas e Convinci-me de que era verdade.</p>"
        "<p>Um segundo paragrafo simples com palavras suficientes para o guarda.</p>"
        "</body></html>",
        "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
        "<p>Andei cinco milhas e Convinci-me de que era verdade.</p>"
        "<p>Um quarto paragrafo simples com palavras suficientes para o guarda.</p>"
        "</body></html>",
    ]
    source = make_epub(tmp_path / "source.epub", chapters=source_chapters)
    target = make_epub(tmp_path / "draft.epub", chapters=draft_chapters)
    output = tmp_path / "refined.epub"

    report = refine_epub(
        str(source),
        str(target),
        str(output),
        model="test-model",
        generate=lambda messages: "Andei duas milhas e convenci-me de que era verdade.",
        limit=1,
    )

    assert report["attempted"] == 1
    assert report["flagged"] >= 2
    assert report["documents_refined"] == 1
