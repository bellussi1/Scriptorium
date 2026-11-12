"""Tests for the pt-PT progressive periphrasis repair ("estou a falar" -> "estou falando")."""
from __future__ import annotations

import zipfile
from pathlib import Path

from src.literary.progressive_repair import (
    repair_progressive_html,
    repair_progressive_in_epub,
)


def _text(html: str) -> str:
    return repair_progressive_html(html)[0]


def test_converts_a_listed_verb_to_the_pt_br_gerund():
    assert _text("<p>Ele estava a falar.</p>") == "<p>Ele estava falando.</p>"


def test_keeps_the_capital_of_the_estar_form_and_the_verb():
    assert _text("<p>Estamos a construir.</p>") == "<p>Estamos construindo.</p>"
    assert _text("<p>Estou a ver.</p>") == "<p>Estou vendo.</p>"


def test_maps_pt_pt_infinitive_spellings_to_pt_br_gerunds():
    assert _text("<p>Estão a detetar sinais.</p>") == "<p>Estão detectando sinais.</p>"
    assert _text("<p>Estou a planear.</p>") == "<p>Estou planejando.</p>"


def test_the_verb_ser_becomes_sendo_in_a_progressive_passive():
    assert _text("<p>Estava a ser atacado.</p>") == "<p>Estava sendo atacado.</p>"


def test_leaves_nouns_that_follow_a_estar_form_alone():
    # "dor" and "favor" end in -r and follow "a" but are nouns here.
    assert _text("<p>Estava a dor de cabeça.</p>") == "<p>Estava a dor de cabeça.</p>"
    assert _text("<p>Estava a favor da ideia.</p>") == "<p>Estava a favor da ideia.</p>"


def test_leaves_the_idiomatic_a_caminho_and_a_bordo_alone():
    html = "<p>Estava a meio caminho. Estava a bordo.</p>"
    assert _text(html) == html


def test_leaves_clitic_forms_alone():
    # The hyphen marks a clitic; the verb is not an independent word here.
    html = "<p>Estou a vê-lo.</p>"
    assert _text(html) == html


def test_never_touches_markup_or_attributes():
    html = '<p title="estava a falar">estava <i>a</i> falar</p>'
    assert _text(html) == html


def test_reports_unlisted_infinitives_for_review():
    _, converted, leftovers = repair_progressive_html(
        "<p>Estavam a lutar e estavam a sonhar com a vitória.</p>"
    )
    assert converted == {"lutar": 1}
    assert leftovers == {"sonhar": 1}


def test_epub_rewrite_changes_only_text_entries(tmp_path: Path):
    source = tmp_path / "in.epub"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("OEBPS/a.xhtml", "<html><body><p>Estou a falar.</p></body></html>")
        archive.writestr("OEBPS/content.opf", "<package>estou a falar</package>")
    out = tmp_path / "out.epub"

    result = repair_progressive_in_epub(str(source), str(out))

    assert result["total_changes"] == 1
    assert [entry["file"] for entry in result["changed_files"]] == ["OEBPS/a.xhtml"]
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist() == ["mimetype", "OEBPS/a.xhtml", "OEBPS/content.opf"]
        assert b"Estou falando." in archive.read("OEBPS/a.xhtml")
        assert archive.read("OEBPS/content.opf") == b"<package>estou a falar</package>"
