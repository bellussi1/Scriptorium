"""Tests for the deterministic dropcap repair."""
from __future__ import annotations

import zipfile
from pathlib import Path

from src.literary.repair import repair_dropcap_html, repair_dropcaps_in_epub


def test_repairs_source_letter_before_translated_word():
    html = '<p><span class="dropcap">A</span>Uma boa tradução.</p>'
    repaired, changes = repair_dropcap_html(html)
    assert repaired == '<p><span class="dropcap">U</span>ma boa tradução.</p>'
    assert len(changes) == 1


def test_repairs_source_letter_before_name():
    html = '<p><span class="dropcap">A</span>Alice começava.</p>'
    repaired, _ = repair_dropcap_html(html)
    assert repaired == '<p><span class="dropcap">A</span>lice começava.</p>'


def test_repairs_whole_word_inside_dropcap():
    html = '<p><span class="dropcap"> estudos</span> servem para o prazer.</p>'
    repaired, _ = repair_dropcap_html(html)
    assert repaired == '<p><span class="dropcap">e</span>studos servem para o prazer.</p>'


def test_repairs_source_letter_before_uppercase_sentence():
    html = '<p><span class="dropcap">T</span>Os editores encerram.</p>'
    repaired, _ = repair_dropcap_html(html)
    assert repaired == '<p><span class="dropcap">O</span>s editores encerram.</p>'


def test_leaves_valid_and_ambiguous_cases_unchanged():
    valid = '<p><span class="dropcap">A</span>lice was tired.</p>'
    assert repair_dropcap_html(valid) == (valid, [])

    empty = '<p><span class="dropcap"/> boa tradução.</p>'
    assert repair_dropcap_html(empty) == (empty, [])

    placeholder = '<p><span class="dropcap">Uma[Alice]</span> começou.</p>'
    assert repair_dropcap_html(placeholder) == (placeholder, [])

    valid_phrase = '<p><span class="dropcap">U</span>ma boa tradução.</p>'
    assert repair_dropcap_html(valid_phrase) == (valid_phrase, [])


def test_repairs_in_epub_and_preserves_other_files(tmp_path: Path):
    source = tmp_path / "in.epub"
    output = tmp_path / "out.epub"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "OEBPS/ch01.xhtml",
            '<html><body><p><span class="dropcap">A</span>Alice começava.</p></body></html>',
        )
        archive.writestr("OEBPS/other.txt", "unchanged")

    report = repair_dropcaps_in_epub(str(source), str(output))

    assert report["total_changes"] == 1
    assert report["changed_files"][0]["file"] == "OEBPS/ch01.xhtml"
    with zipfile.ZipFile(output) as archive:
        html = archive.read("OEBPS/ch01.xhtml").decode("utf-8")
        assert '<span class="dropcap">A</span>lice começava.' in html
        assert archive.read("OEBPS/other.txt") == b"unchanged"
