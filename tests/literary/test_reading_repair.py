"""Tests for the reader-facing EPUB repair pass."""
from __future__ import annotations

import zipfile
from pathlib import Path

from src.literary.reading_repair import (
    _localise_nav,
    _localise_ncx,
    _normalise_package_language,
    _package_title,
    _replace_terms_in_text,
    _title_case,
    convert_dialogue_quotes,
    fix_headings,
    merge_split_paragraphs,
    normalise_straight_quotes,
    paragraph_text,
    repair_reading_epub,
    split_dialogue_paragraphs,
)


def test_merge_joins_a_sentence_split_by_a_chunk_boundary():
    raw = (
        '<p class="x04-Body-Text">Ele olhou para o</p>'
        '<p class="x04-Body-Text">mar e sorriu.</p>'
    )
    repaired, merged = merge_split_paragraphs(raw)
    assert merged == 1
    assert "Ele olhou para o mar e sorriu." in paragraph_text(repaired)
    assert repaired.count("<p") == 1


def test_merge_keeps_a_colon_paragraph_and_capitalises_the_next():
    raw = (
        '<p class="x04-Body-Text">Ele disse:</p>'
        '<p class="x04-Body-Text">existem coisas piores.</p>'
    )
    repaired, merged = merge_split_paragraphs(raw)
    assert merged == 0
    assert repaired.count("<p") == 2
    assert "Existem coisas piores." in paragraph_text(repaired)


def test_merge_keeps_one_word_refrains():
    raw = (
        '<p class="x04-Body-Text">Covarde</p>'
        '<p class="x04-Body-Text">covarde</p>'
        '<p class="x04-Body-Text">covarde.</p>'
    )
    repaired, merged = merge_split_paragraphs(raw)
    assert merged == 0
    assert repaired.count("<p") == 3


def test_convert_dialogue_quotes_to_travessoes():
    raw = '<p class="x04-Body-Text">“Morto?” murmurei.</p>'
    repaired, converted = convert_dialogue_quotes(raw)
    assert converted == 1
    assert paragraph_text(repaired) == "— Morto? — murmurei."


def test_convert_multiple_quote_pairs_in_one_paragraph():
    raw = '<p class="x04-Body-Text">“Não”, disse eu, “mas talvez.”</p>'
    repaired, _ = convert_dialogue_quotes(raw)
    assert paragraph_text(repaired) == "— Não — disse eu — mas talvez."


def test_inline_dialogue_converts_but_a_short_quoted_term_stays():
    dialogue = (
        '<p class="x04-Body-Text">Ela balançou a cabeça. '
        '“Impossível.”</p>'
    )
    repaired, _ = convert_dialogue_quotes(dialogue)
    assert "“Impossível.”" not in paragraph_text(repaired)
    assert "— Impossível." in paragraph_text(repaired)

    term = (
        '<p class="x04-Body-Text">Ele usou a “verdade” do Império.</p>'
    )
    repaired, _ = convert_dialogue_quotes(term)
    assert "“verdade”" in paragraph_text(repaired)


def test_straight_quotes_are_normalised_before_conversion():
    raw = '<p class="x04-Body-Text">"Não", disse eu. "Talvez."</p>'
    normalised, changed, warnings = normalise_straight_quotes(raw)
    assert changed == 1
    assert not warnings
    assert "“Não”" in normalised
    assert "“Talvez.”" in normalised


def test_split_dialogue_keeps_the_travessao_on_the_new_paragraph():
    raw = (
        '<p class="x04-Body-Text">— Primeira fala. — Segunda fala. '
        '— Terceira fala. — Quarta fala.</p>'
    )
    repaired, splits = split_dialogue_paragraphs(raw)
    assert splits == 3
    assert repaired.count("<p") == 4
    assert "— Segunda fala." in paragraph_text(repaired)
    assert "— Quarta fala." in paragraph_text(repaired)


def test_terms_follow_the_official_brazilian_edition():
    counts = {}
    text = _replace_terms_in_text(
        "A Chantry e os Mericanii. Hadrian Halfmortal. Meidua Red Company.",
        counts,
    )
    assert "Chantria" in text
    assert "mericanii" in text
    assert "Hadrian, o Semimortal" in text
    assert "Companhia Vermelha de Meidua" in text
    assert counts


def test_headings_drop_leading_dashes_and_use_the_reader_titles():
    raw = (
        '<h1 class="x03-Chapter-Title">– A COMPANHIA VERMELHA</h1>'
    )
    repaired, changes = fix_headings(
        raw, "OEBPS/xhtml/08_Chapter_1_The_Red_Com.xhtml"
    )
    assert "A COMPANHIA VERMELHA" in repaired
    assert "–" not in repaired
    assert changes


def test_title_case_keeps_small_words_lowercase():
    assert _title_case("À BEIRA DA HISTÓRIA") == "À Beira da História"
    assert _title_case("O MUNDO SOMBRIO") == "O Mundo Sombrio"


def test_package_title_comes_from_the_opf(tmp_path: Path):
    source = tmp_path / "in.epub"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "OEBPS/content.opf",
            "<package><metadata><dc:title>Escuridão Uivante</dc:title>"
            "</metadata></package>",
        )
    assert _package_title(str(source)) == "Escuridão Uivante"


def test_localise_nav_and_ncx_use_the_translated_title():
    nav = (
        '<html><head><title>Demon in White</title></head><body>'
        '<nav epub:type="toc"><ol><li><a href="01_Cover.xhtml">Cover</a></li>'
        '<li><a href="08_Chapter_1_The_Red_Com.xhtml">Chapter I</a></li>'
        "</ol></nav></body></html>"
    )
    repaired = _localise_nav(
        nav,
        {"01_Cover.xhtml": "Capa", "08_Chapter_1_The_Red_Com.xhtml": "Capítulo 1: A Companhia Vermelha"},
        "Demonte em Branco",
    )
    assert "<title>Demonte em Branco</title>" in repaired
    assert ">Capa<" in repaired
    assert ">Capítulo 1: A Companhia Vermelha<" in repaired

    ncx = (
        "<ncx><head/><docTitle><text>Demon in White</text></docTitle><navMap>"
        '<navPoint><content src="01_Cover.xhtml"/><text>Cover</text></navPoint>'
        "</navMap></ncx>"
    )
    fixed = _localise_ncx(ncx, {"01_Cover.xhtml": "Capa"}, "Demonte em Branco")
    assert "<docTitle><text>Demonte em Branco</text></docTitle>" in fixed
    assert "<text>Capa</text>" in fixed


def test_package_language_follows_dc_language():
    opf = (
        '<package version="3.0" xml:lang="en-US"><metadata>'
        "<dc:language>pt-BR</dc:language></metadata></package>"
    )
    assert 'xml:lang="pt-BR"' in _normalise_package_language(opf)


def test_repair_reading_epub_writes_a_valid_copy(tmp_path: Path):
    source = tmp_path / "in.epub"
    output = tmp_path / "out.epub"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "OEBPS/ch01.xhtml",
            '<html><body><p class="x04-Body-Text">“Morto?” murmurei.</p></body></html>',
        )
        archive.writestr(
            "OEBPS/style.css",
            "p.x04-Body-Text { margin: 0; text-indent: 1.3em; }",
        )
        archive.writestr("OEBPS/other.txt", "unchanged")

    report = repair_reading_epub(str(source), str(output))

    assert report["quote_paragraphs"] == 1
    with zipfile.ZipFile(output) as archive:
        html = archive.read("OEBPS/ch01.xhtml").decode("utf-8")
        assert "— Morto? — murmurei." in html
        assert "TBL reader layout" in archive.read("OEBPS/style.css").decode("utf-8")
        assert archive.read("OEBPS/other.txt") == b"unchanged"
