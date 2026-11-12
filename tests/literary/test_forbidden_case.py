"""Case rules for forbidden forms: a lowercase Portuguese word is not a proper-noun hit."""
from __future__ import annotations

from src.literary.per_file_audit import _forbidden_occurrences


def test_lowercase_ordinary_word_is_not_a_hit_for_a_proper_noun_form():
    text = "uma cancao que o futuro cantaria sobre o Devorador do Sol."
    assert _forbidden_occurrences(text, "Cantaria", "Chantry") == 0


def test_capitalised_and_all_caps_proper_noun_forms_still_count():
    assert _forbidden_occurrences("Cantaria e a Ordem.", "Cantaria", "Chantry") == 1
    assert _forbidden_occurrences("A CANTARIA decidiu.", "Cantaria", "Chantry") == 1


def test_english_source_term_counts_in_any_case():
    assert _forbidden_occurrences("O CHANTRY decidiu.", "Chantry", "Chantry") == 1
    assert _forbidden_occurrences("the chantry fell.", "Chantry", "Chantry") == 1
