"""Tests for probe scoring, especially whole-word term matching."""
from __future__ import annotations

from scripts.score_probes import _term_present, score


def test_term_present_does_not_match_longer_derived_words():
    assert _term_present("Ele é jaddiano.", "Jadd") is False
    assert _term_present("Ele é jaddiano.", "Jadd", strict=False) is True
    assert _term_present("Ele é jaddiano.", "jaddiano") is True
    assert _term_present("O povo Jadd.", "Jadd") is True


def test_term_present_accepts_common_portuguese_inflections():
    assert _term_present("Os cielcins chegaram.", "cielcin") is True
    assert _term_present("As chantrias rezam.", "Chantria") is True
    assert _term_present("Os palatinos.", "palatino") is True
    assert _term_present("A legião.", "Legião") is True


def test_score_counts_prefix_term_only_once():
    probes = [
        {
            "id": "p1",
            "kind": "term",
            "series": "The Sun Eater",
            "book": "Empire of Silence",
            "category": "probe",
            "text": "Jaddian and Jadd",
            "reference_pt": "jaddiano e Jadd",
            "expected_terms": [
                {"source": "Jaddian", "target": "jaddiano", "category": "organization"},
                {"source": "Jadd", "target": "Jadd", "category": "location"},
            ],
            "characters": [],
            "character_pool": [],
        }
    ]
    predictions = [
        {
            "id": "p1",
            "generation": {"text": "Ele é jaddiano."},
        }
    ]
    result, detail = score(probes, predictions, strict_terms=True)
    assert detail[0]["term_compliance"] == 0.5
    assert detail[0]["term_hit"] == 1
    assert result["summary"]["term_compliance"] == 0.5

    loose_result, loose_detail = score(probes, predictions, strict_terms=False)
    assert loose_detail[0]["term_hit"] == 2
    assert loose_result["summary"]["term_compliance"] == 1.0


def test_score_detects_missing_term_variant():
    probes = [
        {
            "id": "p2",
            "kind": "term",
            "series": "The Sun Eater",
            "book": "Empire of Silence",
            "category": "probe",
            "text": "Jaddian",
            "reference_pt": "jaddiano",
            "expected_terms": [
                {"source": "Jaddian", "target": "jaddiano", "category": "organization"},
            ],
            "characters": [],
            "character_pool": [],
        }
    ]
    predictions = [{"id": "p2", "generation": {"text": "Ele é jaddiano."}}]
    result, _ = score(probes, predictions, strict_terms=True)
    assert result["summary"]["term_compliance"] == 1.0
