"""Tests for the audit snapshot, drift and validation fallbacks."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("audit_book", ROOT / "scripts" / "audit_book.py")
assert SPEC and SPEC.loader
audit_book = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_book)


def _term(source: str, target: str, **overrides):
    values = {
        "source": source,
        "target": target,
        "category": "concept",
        "aliases": [],
        "alias_targets": {},
        "forbidden": [],
        "accepted_targets": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _book(title: str = "Book"):
    return SimpleNamespace(title=title, series_index=1)


def test_glossary_snapshot_uses_report_asset_then_compiled_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_book, "ROOT", tmp_path)
    compiled = tmp_path / "data" / "compiled" / "some-book-glossary.json"
    compiled.parent.mkdir(parents=True)
    compiled.write_text("{}", encoding="utf-8")

    report = {"assets": {"glossary_host": str(compiled)}}
    assert audit_book._glossary_snapshot_path(report, _book("Some Book")) == compiled
    assert audit_book._glossary_snapshot_path({}, _book("Some Book")) == compiled


def test_glossary_snapshot_is_none_without_report_or_compiled_file(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_book, "ROOT", tmp_path)
    assert audit_book._glossary_snapshot_path({}, _book("Missing")) is None


def test_drifted_term_still_counts_against_the_run_snapshot():
    term = _term("Old Blood", "Sangue Antigo")
    resolved = {
        "terms": [term],
        "current_terms": [_term("Old Blood", "Sangue Antigo")],
        "current_map": {"Old Blood": ("Sangue Antigo", ())},
        "snapshot": "snapshot.json",
        "error": "",
    }

    same = audit_book._term_audit(
        _book(),
        "The old blood was strong.",
        "O Sangue Antigo era forte.",
        resolved=resolved,
    )
    assert same["eligible"] == 1
    assert same["hits"] == 1
    assert same["coverage"] == 1.0
    assert same["drift"] == []

    resolved["current_map"] = {"Old Blood": ("Sangue Velho", ())}
    drifted = audit_book._term_audit(
        _book(),
        "The old blood was strong.",
        "O Sangue Antigo era forte.",
        resolved=resolved,
    )
    assert drifted["eligible"] == 1
    assert drifted["hits"] == 1
    assert drifted["coverage"] == 1.0
    assert len(drifted["drift"]) == 1
    assert drifted["drift"][0]["current_target"] == "Sangue Velho"


def test_report_validation_is_derived_and_stored(tmp_path, monkeypatch):
    report = {"gate_passed": True}
    monkeypatch.setattr(
        audit_book,
        "validate_epub_pair",
        lambda *args, **kwargs: {"passed": True, "blocking": 0},
    )
    validation, backfilled = audit_book._report_validation(
        report, tmp_path / "source.epub", tmp_path / "target.epub"
    )
    assert backfilled is True
    assert validation["passed"] is True
    assert report["validation"]["passed"] is True


def test_existing_report_validation_is_not_overwritten(tmp_path, monkeypatch):
    report = {"validation": {"passed": False, "blocking": 2}}
    monkeypatch.setattr(
        audit_book,
        "validate_epub_pair",
        lambda *args, **kwargs: {"passed": True, "blocking": 0},
    )
    validation, backfilled = audit_book._report_validation(
        report, tmp_path / "source.epub", tmp_path / "target.epub"
    )
    assert backfilled is False
    assert validation["passed"] is False
    assert report["validation"]["blocking"] == 2
