"""Dropcap content checks: the first word must not be lost or duplicated."""
from __future__ import annotations

from src.literary.validation import _dropcap_html_issues


def _codes(html: str) -> list[str]:
    return [issue.code for issue in _dropcap_html_issues(html, "chapter.xhtml")]


def test_valid_dropcap_letter_and_rest_of_word():
    assert _codes('<p><span class="dropcap">A</span>lice was tired.</p>') == []
    assert _codes('<p><span class="dropcap">U</span>ma boa tradução.</p>') == []
    assert _codes('<p><span class="dropcap">A</span> good translation.</p>') == []


def test_empty_self_closing_dropcap_is_an_error():
    assert _codes('<p><span class="dropcap"/> boa tradução.</p>') == ["epub.dropcap_empty"]


def test_full_word_or_placeholder_in_dropcap_is_an_error():
    assert _codes(
        '<p><span class="dropcap">Uma[Alice]</span> começou.</p>'
    ) == ["epub.dropcap_invalid"]


def test_source_letter_left_before_translated_word_is_an_error():
    assert _codes(
        '<p><span class="dropcap">A</span>Uma boa tradução.</p>'
    ) == ["epub.dropcap_letter"]
    assert _codes(
        '<p><span class="dropcap">A</span>Alice começava.</p>'
    ) == ["epub.dropcap_letter"]
