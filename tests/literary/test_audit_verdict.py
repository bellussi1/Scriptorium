"""Tests for the cloud-audit gate: facts fail, style notes advise."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("audit_book", ROOT / "scripts" / "audit_book.py")
assert SPEC and SPEC.loader
audit_book = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_book)


def _item(**overrides):
    item = {
        "id": "sample",
        "alignment_suspect": False,
        "fidelity": 4,
        "naturalness": 4,
        "terminology": 4,
        "register": 4,
        "prose": 4,
        "meaning_errors": 0,
        "style_notes": 0,
        "tense_errors": 0,
        "gender_errors": 0,
        "notes": "",
    }
    item.update(overrides)
    return item


def test_style_notes_do_not_fail_the_book():
    items = [_item(style_notes=1) for _ in range(7)]
    verdict = audit_book._cloud_verdict(items)

    assert verdict["passed"] is True
    assert verdict["style_notes"] == 7
    assert verdict["meaning_errors"] == 0
    assert verdict["warnings"] == []


def test_two_factual_meaning_errors_fail_the_book():
    items = [_item() for _ in range(7)]
    items[0]["meaning_errors"] = 2
    verdict = audit_book._cloud_verdict(items)

    assert verdict["passed"] is False
    assert verdict["meaning_errors"] == 2


def test_one_factual_meaning_error_passes_with_a_warning():
    items = [_item() for _ in range(7)]
    items[0]["meaning_errors"] = 1
    verdict = audit_book._cloud_verdict(items)

    assert verdict["passed"] is True
    assert any("one factual meaning error" in warning for warning in verdict["warnings"])


def test_prose_below_threshold_fails_even_without_meaning_errors():
    items = [_item(prose=3.4) for _ in range(7)]
    verdict = audit_book._cloud_verdict(items)

    assert verdict["passed"] is False
    assert verdict["averages"]["prose"] < 3.5


def test_high_style_note_count_warns_but_passes():
    items = [_item(style_notes=2) for _ in range(7)]
    verdict = audit_book._cloud_verdict(items)

    assert verdict["passed"] is True
    assert verdict["style_notes"] == 14
    assert any("high style-note count" in warning for warning in verdict["warnings"])


def test_alignment_suspect_items_are_not_scored():
    items = [_item() for _ in range(4)] + [
        _item(alignment_suspect=True, prose=1, meaning_errors=5) for _ in range(3)
    ]
    verdict = audit_book._cloud_verdict(items)

    assert verdict["scored_samples"] == 4
    assert verdict["passed"] is True
    assert verdict["meaning_errors"] == 0
    assert verdict["averages"]["prose"] == 4.0


def test_confirmation_can_clear_a_false_positive():
    items = [_item(id=f"s{i}", meaning_errors=1) for i in range(4)]
    all_clear = {
        f"s{i}": {"confirmed_errors": 0, "reason": "the source says the same thing"}
        for i in range(4)
    }
    audit_book._apply_meaning_confirmation(items, all_clear)
    verdict = audit_book._cloud_verdict(items)

    assert verdict["meaning_errors"] == 0
    assert verdict["meaning_candidates"] == 4
    assert verdict["passed"] is True


def test_missing_confirmation_keeps_the_candidate_error():
    items = [_item(id=f"s{i}", meaning_errors=1) for i in range(4)]
    partial = {
        "s0": {"confirmed_errors": 0, "reason": "false positive"},
        "s1": {"confirmed_errors": 1, "reason": "real error"},
    }
    audit_book._apply_meaning_confirmation(items, partial)
    verdict = audit_book._cloud_verdict(items)

    assert verdict["meaning_errors"] == 3
    assert verdict["meaning_candidates"] == 4
    assert verdict["passed"] is False
    assert any("not confirmed" in warning for warning in verdict["warnings"])
