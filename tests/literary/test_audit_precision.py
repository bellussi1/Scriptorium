"""Precision of the audit detectors: Portuguese words must not count as English or forbidden hits."""
from __future__ import annotations

from src.literary.per_file_audit import count_forbidden_occurrences, english_caps_tokens


def test_lowercase_verb_is_not_a_proper_noun_rendering() -> None:
    text = "elas queriam que ela cantaria ao amanhecer."
    assert count_forbidden_occurrences(text, "Cantaria", "Chantry") == 0


def test_capitalised_rendering_is_still_counted() -> None:
    text = "A Cantaria governa o templo."
    assert count_forbidden_occurrences(text, "Cantaria", "Chantry") == 1


def test_english_source_is_matched_in_any_case() -> None:
    assert count_forbidden_occurrences("the chantry bells", "Chantry", "Chantry") == 1


def test_portuguese_for_after_a_conjunction_is_not_english() -> None:
    assert "FOR" not in english_caps_tokens("Se alguém pensar que sim, SE FOR MINOS.")
    assert "FOR" not in english_caps_tokens("QUE FOR o caso")


def test_english_for_is_still_flagged() -> None:
    assert english_caps_tokens("CHAPTER 3 FOR THE EMPIRE") == {"FOR", "THE"}
