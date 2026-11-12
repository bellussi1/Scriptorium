"""Tests for reading the EPUBCheck summary line."""
from __future__ import annotations

from src.literary.queue_runner import parse_epubcheck_counts


def test_singular_warning_is_read():
    text = "Validating using EPUB version 3.4 rules.\nMessages: 0 fatals / 0 errors / 1 warning / 0 infos\n"
    assert parse_epubcheck_counts(text) == {"fatals": 0, "errors": 0, "warnings": 1}


def test_plural_counts_are_read():
    text = "Messages: 0 fatals / 2 errors / 3 warnings / 0 infos\n"
    assert parse_epubcheck_counts(text) == {"fatals": 0, "errors": 2, "warnings": 3}


def test_singular_error_is_read():
    text = "Messages: 0 fatals / 1 error / 0 warnings / 0 infos\n"
    assert parse_epubcheck_counts(text) == {"fatals": 0, "errors": 1, "warnings": 0}


def test_missing_summary_gives_no_counts():
    assert parse_epubcheck_counts("java: not found") == {"fatals": None, "errors": None, "warnings": None}
