from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.literary import chapter_headings as ch


def _paragraphs(markup: str) -> list[ch.Paragraph]:
    return ch.parse_paragraphs(markup)


def test_split_sentences_continues_a_paragraph_without_final_punctuation():
    paragraphs = _paragraphs(
        "<p>First sentence. Second one</p><p>continues here.</p><p>Third starts here. Fourth.</p>"
    )
    sentences = ch.split_sentences(paragraphs)
    assert [s.text for s in sentences] == [
        "First sentence.",
        "Second one continues here.",
        "Third starts here.",
        "Fourth.",
    ]
    assert [s.owner for s in sentences] == [0, 0, 2, 2]


def test_parse_paragraphs_maps_plain_offsets_to_source_positions():
    markup = '<p class="x">Caf&eacute; <b>vermelho</b>.</p>'
    paragraph = _paragraphs(markup)[0]
    assert paragraph.plain == "Café vermelho."
    start, end = paragraph.raw_spans[0]
    assert markup[start:end] == "&eacute;" or markup[start:end] == "C"
    assert paragraph.bold is True


def test_align_lengths_pairs_similar_lengths_one_to_one():
    path = ch.align_lengths([100, 50, 80], [110, 52, 85])
    assert [move for move, _, _ in path] == ["11", "11", "11"]
    assert ch.english_to_translated(path) == {0: 0, 1: 1, 2: 2}


def test_align_lengths_detects_a_merged_translated_sentence():
    path = ch.align_lengths([60, 60, 120], [62, 118])
    mapping = ch.english_to_translated(path)
    assert mapping[0] == 0
    assert mapping[1] == mapping[2] == 1


def test_load_spec_rejects_chapters_out_of_order(tmp_path: Path):
    title_map = tmp_path / "map.yaml"
    title_map.write_text(
        'book: X\nbody_start: {en: "P", pt: "P"}\n'
        'chapters:\n  - {number: 2, en: "A", pt: "A"}\n  - {number: 1, en: "B", pt: "B"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="numbered 1..2"):
        ch.load_spec(title_map)


def test_render_splits_paragraph_and_keeps_its_prose():
    source = '<p class="x">First sentence. Second sentence.</p>'
    paragraph = _paragraphs(source)[0]
    offset = paragraph.plain.index("Second")
    edit = ch._Edit(inserts=[(offset, "<h2>HEAD</h2>")])
    out = ch._render(source, paragraph, edit)
    assert out == '<p class="x">First sentence. </p><h2>HEAD</h2><p class="x">Second sentence.</p>'


def test_render_removes_whole_residue_paragraph_and_puts_heading_there():
    source = '<p class="x">CAPÍTULO UM</p><p class="x">Body text here.</p>'
    residue = _paragraphs(source)[0]
    edit = ch._Edit(removals=[(0, len("CAPÍTULO UM"))], whole=True, inserts=[(0, "<h2>HEAD</h2>")])
    assert ch._render(source, residue, edit) == "<h2>HEAD</h2>"


def test_render_drops_a_paragraph_that_becomes_empty():
    source = '<p class="x">MagiaCAPÍTULO DOIS</p>'
    paragraph = _paragraphs(source)[0]
    edit = ch._Edit(removals=[(0, len("MagiaCAPÍTULO DOIS"))])
    assert ch._render(source, paragraph, edit) == ""


def test_locate_residue_accepts_contiguous_pieces_and_rejects_mid_text():
    markup = "<p>Body before. </p><p>MagiaCAPÍTULO DOIS</p><p>VIVOSO SERPENTE</p>"
    paragraphs = _paragraphs(markup)
    found = ch.locate_residue(paragraphs, ["MagiaCAPÍTULO DOIS", "VIVOS"], (0, 0), 5, chapter=2)
    assert [(piece, para) for piece, para, _, _ in found] == [("MagiaCAPÍTULO DOIS", 1), ("VIVOS", 2)]
    with pytest.raises(ValueError, match="not found"):
        ch.locate_residue(paragraphs, ["SERPENTE"], (0, 0), 5, chapter=2)


def test_build_ncx_nests_chapters_under_their_part():
    ncx = (
        '<?xml version="1.0"?><ncx><docTitle><text>Book</text></docTitle>'
        "<navMap><navPoint id=\"old\"/></navMap></ncx>"
    )
    anchor = ch.Position("index_split_000.html", 0, 0)
    plans = [
        ch.ChapterPlan(1, "A", "Alfa", anchor, part={"number": 1, "pt": "Verão"}),
        ch.ChapterPlan(2, "B", "Beta", anchor),
    ]
    out = ch.build_ncx(ncx, plans, {"parts": []})
    assert out.count("<navPoint ") == 3
    assert "<text>Parte 1 VERÃO</text>" in out
    part_open = out.index("Parte 1 VERÃO")
    chapter_one = out.index("Capítulo 1 ALFA")
    chapter_two = out.index("Capítulo 2 BETA")
    assert part_open < chapter_one < chapter_two
    assert out.count("</navPoint>") == 3
    assert "<navMap>" in out and out.endswith("</ncx>")


def _write_epub(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, text in members.items():
            archive.writestr(name, text)


def test_restore_epub_inserts_headings_and_rebuilds_ncx(tmp_path: Path):
    spec = tmp_path / "map.yaml"
    spec.write_text(
        'book: Tiny\nbody_start: {en: "PROLOGUE - START", pt: "PRÓLOGO"}\n'
        'chapters:\n'
        '  - {number: 1, en: "Alpha", pt: "Alfa", residue: ["CAPÍTULO UM - ALPHA"]}\n'
        '  - {number: 2, en: "Beta", pt: "Beta"}\n',
        encoding="utf-8",
    )
    en_epub = tmp_path / "en.epub"
    pt_epub = tmp_path / "pt.epub"
    en_body = (
        '<p>PROLOGUE - START</p>'
        '<p>The river ran cold past the old mill. Nobody came to fish there anymore.</p>'
        '<p><b>CHAPTER ONE - ALPHA</b></p>'
        '<p>The boat drifted under the bridge. Mara watched it go by in silence.</p>'
        '<p><b>CHAPTER TWO - BETA</b></p>'
        '<p>Morning came slowly over the hills. Everyone was awake before the bell.</p>'
    )
    pt_body = (
        '<p>PRÓLOGO</p>'
        '<p>O rio corria frio além do velho moinho. Ninguém mais ia pescar ali.</p>'
        '<p>CAPÍTULO UM - ALPHA</p>'
        '<p>O barco deslizou sob a ponte. Mara observou-o partir em silêncio.</p>'
        '<p>A manhã chegou devagar sobre as colinas. Todos estavam acordados antes do sino.</p>'
    )
    _write_epub(en_epub, {"index_split_000.html": en_body, "toc.ncx": "<ncx/>"})
    ncx = (
        '<?xml version="1.0"?><ncx><navMap><navPoint id="x"><navLabel><text>Old</text></navLabel>'
        '<content src="index_split_000.html"/></navPoint></navMap></ncx>'
    )
    _write_epub(pt_epub, {"index_split_000.html": f"<html><body>{pt_body}</body></html>", "toc.ncx": ncx})
    out = tmp_path / "out.epub"

    report = ch.restore_epub(en_epub, pt_epub, spec, out)

    with zipfile.ZipFile(out) as archive:
        body = archive.read("index_split_000.html").decode("utf-8")
        toc = archive.read("toc.ncx").decode("utf-8")
    assert 'id="chapter-1"' in body and 'id="chapter-2"' in body
    assert "CAPÍTULO UM - ALPHA" not in body
    assert body.index("chapter-1") < body.index("O barco deslizou") < body.index("chapter-2")
    assert "<text>Capítulo 1 ALFA</text>" in toc and "<text>Capítulo 2 BETA</text>" in toc
    assert [c["number"] for c in report["chapters"]] == [1, 2]
    assert "Old" not in toc
