"""Tests for the chapter-title and exact-edit post-pass."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.literary.chapter_titles import (
    apply_epub_edits,
    chapter_label,
    load_title_map,
    relabel_epub,
)

ROOT = Path(__file__).resolve().parents[2]
DEMON_MAP = ROOT / "literary-resources" / "christopher-ruocchio" / "sun-eater" / "chapter-titles" / "demon-in-white.yaml"
KINGDOMS_MAP = ROOT / "literary-resources" / "christopher-ruocchio" / "sun-eater" / "chapter-titles" / "kingdoms-of-death.yaml"

NAV = (
    '<html xmlns:epub="http://www.idpf.org/2007/ops"><body>'
    '<nav epub:type="toc"><ol>'
    '<li><a href="xhtml/07_Chapter_1_Behold.xhtml">CAPÍTULO 1</a></li>'
    '<li><a href="xhtml/08_Chapter_2_Majesty.xhtml">CAPÍTULO 2</a></li>'
    '<li><a href="xhtml/06_Contents.xhtml">CONTEÚDO</a></li>'
    "</ol></nav>"
    '<nav epub:type="page-list"><ol>'
    '<li><a href="xhtml/07_Chapter_1_Behold.xhtml#p1">1</a></li>'
    "</ol></nav></body></html>"
)

NCX = (
    '<?xml version="1.0"?><ncx><navMap>'
    '<navPoint id="n1"><navLabel><text>CAPÍTULO 1</text></navLabel>'
    '<content src="xhtml/07_Chapter_1_Behold.xhtml"/></navPoint>'
    '<navPoint id="n2"><navLabel><text>CAPÍTULO 2</text></navLabel>'
    '<content src="xhtml/08_Chapter_2_Majesty.xhtml"/></navPoint>'
    "</navMap><pageList>"
    '<pageTarget id="p"><navLabel><text>1</text></navLabel>'
    '<content src="xhtml/07_Chapter_1_Behold.xhtml#p1"/></pageTarget>'
    "</pageList></ncx>"
)


def _make_epub(path: Path, *, first_title: str = "Chapter 1: Behold a Pale Horse, Book X") -> Path:
    files = {
        "OEBPS/xhtml/07_Chapter_1_Behold.xhtml": f"<html><head><title>{first_title}</title></head><body><h1>CAPÍTULO 1</h1></body></html>",
        "OEBPS/xhtml/08_Chapter_2_Majesty.xhtml": "<html><head><title>Chapter 2: Majesty, Monarch, Prophet, Princess, Book X</title></head><body><h1>CAPÍTULO 2</h1></body></html>",
        "OEBPS/xhtml/06_Contents.xhtml": "<html><head><title>CONTEÚDO</title></head><body/></html>",
        "OEBPS/xhtml/96_Lexicon.xhtml": "<html><head><title>Léxico</title></head><body><table><tr><td><p><b>Chantry</b></p></td></tr></table></body></html>",
        "OEBPS/nav.xhtml": NAV,
        "OEBPS/toc.ncx": NCX,
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, text in files.items():
            archive.writestr(name, text)
    return path


def _titles(*, first_en: str = "Behold a Pale Horse", second_en: str = "Majesty, Monarch, Prophet, Princess") -> dict:
    return {
        "book": "Book X",
        "series": "",
        "series_index": None,
        "chapters": {
            1: {"en": first_en, "pt": "Eis um Cavalo Pálido"},
            2: {"en": second_en, "pt": "Majestade, Monarca, Profeta, Princesa"},
        },
    }


def _read(path: Path, member: str) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read(member).decode("utf-8")


def test_retitles_chapters_toc_and_ncx_but_not_page_list(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub")
    output = tmp_path / "out.epub"

    report = apply_epub_edits(source, output, titles=_titles())

    assert report["chapters_retitled"] == 2
    assert report["toc_labels"] == 2
    assert report["ncx_labels"] == 2
    assert "<title>Capítulo 1 EIS UM CAVALO PÁLIDO</title>" in _read(output, "OEBPS/xhtml/07_Chapter_1_Behold.xhtml")
    assert "<title>Capítulo 2 MAJESTADE, MONARCA, PROFETA, PRINCESA</title>" in _read(
        output, "OEBPS/xhtml/08_Chapter_2_Majesty.xhtml"
    )
    nav = _read(output, "OEBPS/nav.xhtml")
    assert ">Capítulo 1 EIS UM CAVALO PÁLIDO</a>" in nav
    assert ">CONTEÚDO</a>" in nav, "non-chapter TOC entries stay as they are"
    assert '<a href="xhtml/07_Chapter_1_Behold.xhtml#p1">1</a>' in nav, "page-list labels are not chapter labels"
    ncx = _read(output, "OEBPS/toc.ncx")
    assert "<text>Capítulo 1 EIS UM CAVALO PÁLIDO</text>" in ncx
    assert "<navLabel><text>1</text></navLabel>" in ncx


def test_relabel_moves_legacy_labels_and_keeps_body(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub", first_title="Capítulo 1: Ação &amp; Fim")
    output = tmp_path / "out.epub"
    # The NCX and TOC carry the legacy label too.
    with zipfile.ZipFile(source) as archive:
        members = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    members["OEBPS/toc.ncx"] = members["OEBPS/toc.ncx"].replace("CAPÍTULO 1".encode(), "Capítulo 1: Ação &amp; Fim".encode())
    members["OEBPS/nav.xhtml"] = members["OEBPS/nav.xhtml"].replace("CAPÍTULO 1".encode(), "Capítulo 1: Ação &amp; Fim".encode())
    with zipfile.ZipFile(source, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)

    report = relabel_epub(source, output)

    assert report["title_elements"] == 1
    assert report["toc_labels"] == 1
    assert report["ncx_labels"] == 1
    assert "<title>Capítulo 1 AÇÃO &amp; FIM</title>" in _read(output, "OEBPS/xhtml/07_Chapter_1_Behold.xhtml")
    assert ">Capítulo 1 AÇÃO &amp; FIM</a>" in _read(output, "OEBPS/nav.xhtml")
    assert "<text>Capítulo 1 AÇÃO &amp; FIM</text>" in _read(output, "OEBPS/toc.ncx")
    assert "<h1>CAPÍTULO 1</h1>" in _read(output, "OEBPS/xhtml/07_Chapter_1_Behold.xhtml"), "body is untouched"


def test_relabel_takes_pt_titles_from_map(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub", first_title="Capítulo 1: Céu Crepuscular")
    output = tmp_path / "out.epub"

    report = relabel_epub(source, output, titles=_titles())

    assert report["title_elements"] == 1
    chapter = _read(output, "OEBPS/xhtml/07_Chapter_1_Behold.xhtml")
    assert "<title>Capítulo 1 EIS UM CAVALO PÁLIDO</title>" in chapter
    assert "Céu Crepuscular" not in chapter


def test_relabel_with_map_refuses_chapter_missing_from_map(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub", first_title="Capítulo 3: Outro")
    output = tmp_path / "out.epub"

    with pytest.raises(ValueError, match="no pt-BR title for chapter 3"):
        relabel_epub(source, output, titles=_titles())
    assert not output.exists()


def test_mimetype_stays_first_and_stored(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub")
    output = tmp_path / "out.epub"

    apply_epub_edits(source, output, titles=_titles())

    with zipfile.ZipFile(output) as archive:
        first = archive.infolist()[0]
    assert first.filename == "mimetype"
    assert first.compress_type == zipfile.ZIP_STORED


def test_apostrophes_are_compared_as_ascii(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub", first_title="Chapter 1: Gabriel’s Archive, Book X")
    output = tmp_path / "out.epub"

    report = apply_epub_edits(source, output, titles=_titles(first_en="Gabriel's Archive"))

    assert report["chapters_retitled"] == 2


def test_title_mismatch_writes_nothing(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub")
    output = tmp_path / "out.epub"

    with pytest.raises(ValueError, match="does not match"):
        apply_epub_edits(source, output, titles=_titles(first_en="Behold a Pale Rider"))
    assert not output.exists()


def test_exact_edit_applies_once(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub")
    output = tmp_path / "out.epub"

    report = apply_epub_edits(
        source,
        output,
        edits=[("OEBPS/xhtml/96_Lexicon.xhtml", "<b>Chantry</b>", "<b>Chantria</b>")],
    )

    assert report["text_edits"][0]["file"] == "OEBPS/xhtml/96_Lexicon.xhtml"
    assert "<b>Chantria</b>" in _read(output, "OEBPS/xhtml/96_Lexicon.xhtml")
    assert "<b>Chantry</b>" not in _read(output, "OEBPS/xhtml/96_Lexicon.xhtml")


def test_edit_with_no_match_is_refused(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub")
    output = tmp_path / "out.epub"

    with pytest.raises(ValueError, match="found 0"):
        apply_epub_edits(source, output, edits=[("OEBPS/xhtml/96_Lexicon.xhtml", "<b>Nope</b>", "x")])
    assert not output.exists()


def test_edit_matching_twice_is_refused(tmp_path: Path) -> None:
    source = _make_epub(tmp_path / "in.epub")
    output = tmp_path / "out.epub"

    with pytest.raises(ValueError, match="found 2"):
        apply_epub_edits(source, output, edits=[("OEBPS/nav.xhtml", "07_Chapter_1_Behold.xhtml", "X")])
    assert not output.exists()


def test_demon_in_white_title_map_is_complete() -> None:
    data = load_title_map(DEMON_MAP)

    assert data["book"] == "Demon in White"
    assert data["series"] == "The Sun Eater"
    assert data["series_index"] == 3.0
    assert sorted(data["chapters"]) == list(range(1, 88))
    assert data["chapters"][66]["pt"] == "Império do Silêncio"


def test_kingdoms_of_death_title_map_is_complete() -> None:
    data = load_title_map(KINGDOMS_MAP)

    assert data["book"] == "Kingdoms of Death"
    assert data["series"] == "The Sun Eater"
    assert data["series_index"] == 4.0
    assert len(data["chapters"]) == 51, "the source EPUB has 51 chapter files"
    assert sorted(data["chapters"]) == list(range(1, 52))
    assert data["chapters"][51]["pt"] == "A Glória do Mundo"


def test_chapter_label_defaults_to_arabic_numerals() -> None:
    assert chapter_label(7, "Coração de Lobo") == "Capítulo 7 CORAÇÃO DE LOBO"


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (1, "I"),
        (4, "IV"),
        (9, "IX"),
        (14, "XIV"),
        (21, "XXI"),
        (28, "XXVIII"),
        (29, "XXIX"),
        (40, "XL"),
    ],
)
def test_chapter_label_roman_numerals(number: int, expected: str) -> None:
    assert chapter_label(number, "Coração de Lobo", numeral="roman") == f"Capítulo {expected} CORAÇÃO DE LOBO"


def test_chapter_label_rejects_unknown_numeral_style() -> None:
    with pytest.raises(ValueError, match="numeral must be"):
        chapter_label(7, "Coração de Lobo", numeral="letters")


def test_chapter_label_rejects_zero_as_roman_numeral() -> None:
    with pytest.raises(ValueError, match="start at 1"):
        chapter_label(0, "Prólogo", numeral="roman")
