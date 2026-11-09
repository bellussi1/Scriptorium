"""Tests for the probe scorer's short-form and swap handling."""
from __future__ import annotations

from scripts.score_probes import score


def _probe(probe_id: str, expected: dict, characters: list[str], pool: list[str]) -> dict:
    return {
        "id": probe_id,
        "kind": "name",
        "series": "Test",
        "book": "Test Book",
        "expected_terms": [expected],
        "characters": characters,
        "character_pool": pool,
        "reference_pt": "",
    }


def test_short_form_counts_as_the_same_character():
    probe = _probe(
        "probe-1",
        {"source": "King Shrewd", "target": "Rei Shrewd", "category": "character"},
        ["Rei Shrewd"],
        ["Rei Shrewd", "Shrewd", "Fitz"],
    )
    prediction = {"id": "probe-1", "generation": {"text": "Shrewd olhou para Fitz."}}

    result, details = score([probe], [prediction])

    assert result["summary"]["name_hit"] == 1
    assert result["summary"]["swaps"] == 0
    assert details[0]["name_swap"] is False


def test_a_different_character_is_a_swap():
    probe = _probe(
        "probe-2",
        {"source": "Aquilus", "target": "Aquilus", "category": "character"},
        ["Aquilus"],
        ["Aquilus", "Gar"],
    )
    prediction = {"id": "probe-2", "generation": {"text": "Gar entrou na sala."}}

    result, details = score([probe], [prediction])

    assert result["summary"]["name_hit"] == 0
    assert result["summary"]["swaps"] == 1
    assert details[0]["name_swap"] is True
