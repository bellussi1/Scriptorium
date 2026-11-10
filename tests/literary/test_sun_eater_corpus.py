"""Tests for the Sun Eater corpus builder and generated artifacts."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.build_sun_eater_corpus import (
    SimpleTerm,
    _chapter_number,
    load_sun_terms,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "benchmark" / "literary"


def test_chapter_number_accepts_english_and_portuguese_titles():
    assert _chapter_number("Chapter 1: Hadrian") == 1
    assert _chapter_number("Capítulo 12 A FEIURA DO MUNDO") == 12
    assert _chapter_number("Cover") is None
    assert _chapter_number("") is None


def test_simple_term_aliases_and_targets():
    term = SimpleTerm(
        {
            "source": "Cielcin",
            "target": "cielcin",
            "category": "other",
            "aliases": ["Cielcins"],
            "alias_targets": {"Cielcins": "cielcins"},
        }
    )
    assert term.source_forms() == ["Cielcin", "Cielcins"]
    assert term.target_for_form("Cielcins") == "cielcins"
    assert term.target_for_form("Cielcin") == "cielcin"


def test_sun_eater_resources_include_confirmed_characters_and_terms():
    terms = load_sun_terms()
    assert len(terms) == 75
    assert sum(1 for term in terms if term.category == "character") == 24
    by_source = {term.source: term for term in terms}
    assert by_source["Hadrian Marlowe"].target == "Hadrian Marlowe"
    assert by_source["Cielcin"].target == "cielcin"
    assert by_source["Sollan Empire"].target == "Império Sollano"
    assert by_source["Empire of Silence"].target == "Império do Silêncio"


@pytest.mark.skipif(
    not (OUT / "eval_sun_eater_dev.jsonl").exists(),
    reason="Sun Eater corpus has not been generated in this checkout",
)
def test_generated_sun_eater_corpus_shape():
    dev = [json.loads(line) for line in (OUT / "eval_sun_eater_dev.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    test = [json.loads(line) for line in (OUT / "eval_sun_eater_test.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(dev) == 56
    assert len(test) == 28
    assert Counter(row["category"] for row in dev) == Counter({category: 8 for category in {
        "dialogue", "introspection", "description", "action", "long_syntax", "irony", "terminology",
    }})
    assert Counter(row["category"] for row in test) == Counter({category: 4 for category in {
        "dialogue", "introspection", "description", "action", "long_syntax", "irony", "terminology",
    }})
    assert all(row["reference_pt"] for row in dev + test)
    assert all(row["text"] and row["book"] == "Empire of Silence" for row in dev + test)


@pytest.mark.skipif(
    not (OUT / "probes_run_sun_eater.jsonl").exists(),
    reason="Sun Eater probes have not been generated in this checkout",
)
def test_generated_sun_eater_probes_have_official_coverage():
    rows = [json.loads(line) for line in (OUT / "probes_run_sun_eater.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 50
    assert {row["kind"] for row in rows} == {"name", "term"}
    assert all(row["reference_kind"] == "official_pt" for row in rows)
    assert all((row.get("reference_coverage") or 0) >= 0.66 for row in rows)
    assert all(row["expected_terms"] for row in rows)
