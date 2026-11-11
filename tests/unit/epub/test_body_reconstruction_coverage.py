"""The XML reconstruction reports how much of the translated text it kept.

A passage the parser drops must lower the coverage and produce a warning, and
a clean reconstruction must stay silent. The normal output is not changed.
"""
from lxml import etree

from src.core.epub import body_serializer

XHTML = "http://www.w3.org/1999/xhtml"


def _body():
    doc = etree.fromstring(
        f"<html xmlns='{XHTML}'><body><p>old</p></body></html>".encode("utf-8"))
    return doc.find(f"{{{XHTML}}}body")


def test_clean_reconstruction_has_full_coverage_and_no_warning(monkeypatch):
    warnings = []
    monkeypatch.setattr(body_serializer, "warning", lambda message, *a, **k: warnings.append(message))

    coverage = body_serializer.replace_body_content(
        _body(), "<p>Olá, mundo.</p><p>Segunda linha.</p>")

    assert coverage == 1.0
    assert warnings == []


def test_dropped_passage_lowers_coverage_and_warns(monkeypatch):
    warnings = []
    monkeypatch.setattr(body_serializer, "warning", lambda message, *a, **k: warnings.append(message))

    # An undefined XML entity is dropped by the recovering parser, with its text.
    coverage = body_serializer.replace_body_content(
        _body(), "<p>Início &hellip; fim da frase importante.</p>")

    assert coverage < body_serializer.RECONSTRUCTION_COVERAGE_WARN
    assert len(warnings) == 1
    assert "kept" in warnings[0] and "%" in warnings[0]


def test_coverage_is_one_for_markup_without_visible_text():
    assert body_serializer.markup_text_coverage("<br/><img src='x'/>", etree.Element("x")) == 1.0


def test_coverage_counts_visible_characters_not_whitespace():
    parsed = etree.fromstring(f"<temp xmlns='{XHTML}'><p>ab cd</p></temp>")

    assert body_serializer.markup_text_coverage("<p>ab\n  cd</p>", parsed) == 1.0
    assert body_serializer.markup_text_coverage("<p>ab cdef</p>", parsed) == 4 / 6
