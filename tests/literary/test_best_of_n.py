"""Tests for deterministic best-of-N selection."""
from __future__ import annotations

import pytest

from src.literary.best_of_n import score_candidate, select_best
from src.literary.models import CompiledResources, GlossaryBundle, Term


def _compiled() -> CompiledResources:
    return CompiledResources(
        glossary=GlossaryBundle(
            terms=[
                Term(
                    source="Fugue",
                    target="Fuga",
                    category="concept",
                    policy="translate",
                    confidence="confirmed",
                    approved=True,
                )
            ]
        )
    )


def test_best_candidate_wins_on_names_numbers_and_language():
    source = "I woke from the Fugue and walked two miles down the road."
    good = "Acordei da Fuga e caminhei duas milhas pela estrada."
    literal = "Eu acordei do estado de fuga e andei duas milhas pela estrada."
    english = "I woke from the Fugue and walked two miles down the road."

    result = select_best(
        source,
        [english, literal, good],
        compiled=_compiled(),
    )

    assert result["selected"]["text"] == good
    assert result["fallback"] is False
    assert result["eligible_count"] >= 1
    assert result["candidates"][0]["text"] == good
    english_metrics = next(item for item in result["candidates"] if item["text"] == english)
    assert english_metrics["eligible"] is False
    assert "detected_as_english" in english_metrics["reasons"]


def test_missing_glossary_target_is_penalized():
    source = "The Fugue was a strange state."
    with_term = "A Fuga era um estado estranho."
    without_term = "O estado era estranho."

    good = score_candidate(source, with_term, compiled=_compiled())
    bad = score_candidate(source, without_term, compiled=_compiled())

    assert good.metrics["name_recall"] == 1.0
    assert bad.metrics["name_recall"] == 0.0
    assert good.score > bad.score
    assert bad.eligible is False
    assert "glossary_recall_below_0.50" in bad.reasons


def test_grammar_errors_reduce_the_score_without_making_the_candidate_ineligible():
    source = "I convinced myself that it was true."
    correct = "Convenci-me de que era verdade."
    wrong = "Convinci-me de que era verdade."

    good = score_candidate(source, correct, compiled=_compiled())
    bad = score_candidate(source, wrong, compiled=_compiled())

    assert good.metrics["grammar_errors"] == 0
    assert bad.metrics["grammar_errors"] == 1
    assert good.score > bad.score
    assert bad.eligible is True


def test_empty_candidate_list_raises():
    with pytest.raises(ValueError):
        select_best("source", [])


def test_all_ineligible_candidates_return_a_fallback():
    result = select_best(
        "I woke from the Fugue and walked two miles down the road.",
        ["I woke from the Fugue and walked two miles down the road.", ""],
    )
    assert result["fallback"] is True
    assert result["selected"]["eligible"] is False


def test_ties_are_broken_by_generation_order():
    source = "A simple sentence."
    first = "Uma frase simples."
    second = "Uma frase simples."
    result = select_best(source, [first, second])
    assert result["selected"]["index"] == 0
    assert result["selected"]["text"] == first
