"""Tests for the digit-leading id repair (EPUBCheck RSC-005 / RSC-012)."""
from __future__ import annotations

import zipfile
from pathlib import Path

from src.literary.repair import _invalid_xml_id, repair_invalid_ids_in_epub

OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata/>
  <manifest/>
  <spine/>
  <guide>
    <reference type="toc" href="text/part1.xhtml#2abc" title="Table of Contents"/>
  </guide>
</package>
"""

PART1 = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
    '<h2 id="2abc">Contents</h2>'
    '<a href="#2abc">back</a><a href="part2.xhtml#chapter-2">next</a>'
    "</body></html>"
)

PART2 = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
    '<h2 id="chapter-2">Two</h2><p data-id="9x">kept</p>'
    "</body></html>"
)


def _write_epub(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return path


def _read(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8")


def test_renames_a_digit_leading_id_and_every_fragment_reference(tmp_path):
    source = _write_epub(
        tmp_path / "in.epub",
        {"content.opf": OPF, "text/part1.xhtml": PART1, "text/part2.xhtml": PART2},
    )
    out = tmp_path / "out.epub"
    result = repair_invalid_ids_in_epub(str(source), str(out))

    assert result["renamed_ids"] == {"2abc": "_2abc"}
    assert result["total_changes"] == 3  # the id, the same-file href, the guide reference
    part1 = _read(out, "text/part1.xhtml")
    assert 'id="_2abc"' in part1
    assert 'href="#_2abc"' in part1
    assert "2abc" in part1 and 'id="2abc"' not in part1
    opf = _read(out, "content.opf")
    assert 'href="text/part1.xhtml#_2abc"' in opf
    assert "#2abc" not in opf


def test_leaves_valid_ids_and_other_documents_untouched(tmp_path):
    source = _write_epub(
        tmp_path / "in.epub",
        {"content.opf": OPF, "text/part1.xhtml": PART1, "text/part2.xhtml": PART2},
    )
    out = tmp_path / "out.epub"
    repair_invalid_ids_in_epub(str(source), str(out))

    part2 = _read(out, "text/part2.xhtml")
    assert part2 == PART2
    assert 'href="part2.xhtml#chapter-2"' in _read(out, "text/part1.xhtml")


def test_a_rename_never_collides_with_an_existing_id(tmp_path):
    clash = PART2.replace("chapter-2", "_2abc")
    source = _write_epub(
        tmp_path / "in.epub",
        {"content.opf": OPF, "text/part1.xhtml": PART1, "text/part2.xhtml": clash},
    )
    result = repair_invalid_ids_in_epub(str(source), str(tmp_path / "out.epub"))
    assert result["renamed_ids"] == {"2abc": "__2abc"}
    assert 'id="_2abc"' in _read(tmp_path / "out.epub", "text/part2.xhtml")


def test_an_epub_without_bad_ids_is_copied_with_no_changes(tmp_path):
    clean = PART1.replace("2abc", "abc")
    opf = OPF.replace("#2abc", "#abc")
    source = _write_epub(
        tmp_path / "in.epub",
        {"content.opf": opf, "text/part1.xhtml": clean, "text/part2.xhtml": PART2},
    )
    result = repair_invalid_ids_in_epub(str(source), str(tmp_path / "out.epub"))
    assert result["total_changes"] == 0
    assert result["renamed_ids"] == {}
    assert _read(tmp_path / "out.epub", "text/part1.xhtml") == clean


def test_xml_name_rule():
    assert _invalid_xml_id("2abc") is True
    assert _invalid_xml_id("-x") is True
    assert _invalid_xml_id("abc") is False
    assert _invalid_xml_id("_x") is False
    assert _invalid_xml_id("émile1") is False
    assert _invalid_xml_id("") is False
