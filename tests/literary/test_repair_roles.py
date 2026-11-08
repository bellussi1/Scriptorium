"""Tests for the DPUB-ARIA role repair."""
from __future__ import annotations

import zipfile
from pathlib import Path

from src.literary.repair import (
    repair_doc_roles_in_epub,
    repair_invalid_doc_roles_html,
)

from .conftest import make_epub


def test_removes_only_body_doc_roles():
    html = (
        '<html><body epub:type="cover" role="doc-cover" class="cover">'
        "<p>Cover</p></body></html>"
    )
    repaired, changes = repair_invalid_doc_roles_html(html)
    assert 'role="doc-cover"' not in repaired
    assert 'epub:type="cover"' in repaired
    assert 'class="cover"' in repaired
    assert len(changes) == 1


def test_leaves_non_body_doc_roles_alone():
    html = '<html><body><section role="doc-chapter"><p>Text</p></section></body></html>'
    repaired, changes = repair_invalid_doc_roles_html(html)
    assert repaired == html
    assert changes == []


def test_repair_in_epub(tmp_path: Path):
    chapters = [
        "<html xmlns='http://www.w3.org/1999/xhtml'><body epub:type='cover' role='doc-cover'>"
        "<p>Cover</p></body></html>",
        "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
        "<p>Text</p></body></html>",
    ]
    source = make_epub(tmp_path / "source.epub", chapters=chapters)
    output = tmp_path / "repaired.epub"

    report = repair_doc_roles_in_epub(str(source), str(output))

    assert report["total_changes"] == 1
    with zipfile.ZipFile(output) as archive:
        cover = archive.read("OEBPS/ch1.xhtml").decode("utf-8")
    assert 'role="doc-cover"' not in cover
    assert "epub:type='cover'" in cover
