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
    # The universe glossary grows as later books are prepared; the exact count
    # is not a contract. The confirmed core terms below are.
    assert len(terms) >= 75
    assert sum(1 for term in terms if term.category == "character") >= 24
    by_source = {term.source: term for term in terms}
    assert by_source["Hadrian Marlowe"].target == "Hadrian Marlowe"
    assert by_source["Cielcin"].target == "cielcin"
    assert by_source["Sollan Empire"].target == "Império Sollano"
    assert by_source["Empire of Silence"].target == "Império do Silêncio"
    assert by_source["Quiet"].target == "Quietos"
    assert by_source["Pale"].target == "pálido"
    assert by_source["Forum"].target == "Fórum"
    assert by_source["Gibson of Syracuse"].target == "Gibson de Siracusa"


def test_book_one_glossary_covers_every_probe_term():
    from src.literary.resources import compile_for_book, load_tree

    tree = load_tree(str(ROOT / "literary-resources"))
    compiled = compile_for_book(
        tree, "christopher-ruocchio", "sun-eater", "", "empire-of-silence"
    )
    prompt_forms = {term.source for term in compiled.glossary.terms}
    prompt_forms.update(alias for term in compiled.glossary.terms for alias in term.aliases)
    probes_path = OUT / "probes_run_sun_eater.jsonl"
    if not probes_path.exists():
        pytest.skip("Sun Eater probes have not been generated in this checkout")
    probes = [
        json.loads(line)
        for line in probes_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    missing = {
        term["source"]
        for probe in probes
        for term in probe["expected_terms"]
        if term["source"] not in prompt_forms
    }
    assert not missing, f"probe terms missing from the book-one glossary: {sorted(missing)}"


def test_benchmark_prompt_uses_alias_targets():
    from scripts.benchmark_fase_d import _resources

    glossary, style = _resources(
        "christopher-ruocchio", "sun-eater", "", "Empire of Silence", 1
    )
    assert glossary["Hadrian"] == "Hadrian"
    assert glossary["Marlowe"] == "Marlowe"
    assert glossary["Gibson"] == "Gibson"
    assert glossary["Gibson of Syracuse"] == "Gibson de Siracusa"
    assert glossary["Emperor William"] == "imperador William"
    assert glossary["Quiet"] == "Quietos"
    assert glossary["Pale"] == "pálido"
    assert glossary["Forum"] == "Fórum"
    assert len(glossary) >= 60
    assert style


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
    not (OUT / "eval_sun_eater_dev.jsonl").exists(),
    reason="Sun Eater corpus has not been generated in this checkout",
)
def test_generated_sun_eater_splits_do_not_overlap():
    dev = [json.loads(line) for line in (OUT / "eval_sun_eater_dev.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    test = [json.loads(line) for line in (OUT / "eval_sun_eater_test.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert not ({row["id"] for row in dev} & {row["id"] for row in test})
    assert not ({row["text"] for row in dev} & {row["text"] for row in test})
    assert len({row["text"] for row in dev}) == len(dev)
    assert len({row["text"] for row in test}) == len(test)
    for row in dev + test:
        assert 0.65 <= row["alignment"]["ratio"] <= 1.55
        assert row["alignment"]["confidence"] in {"high", "medium"}
        assert row["word_count"] >= 10


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
    assert len({row["text"] for row in rows}) == len(rows)


@pytest.mark.skipif(
    not (OUT / "probes_run_sun_eater.jsonl").exists()
    or not (OUT / "eval_sun_eater_dev.jsonl").exists(),
    reason="Sun Eater corpus has not been generated in this checkout",
)
def test_generated_sun_eater_probes_do_not_reuse_corpus_text():
    probes = [json.loads(line) for line in (OUT / "probes_run_sun_eater.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    dev = [json.loads(line) for line in (OUT / "eval_sun_eater_dev.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    test = [json.loads(line) for line in (OUT / "eval_sun_eater_test.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    corpus_texts = {row["text"] for row in dev + test}
    assert not ({row["text"] for row in probes} & corpus_texts)


@pytest.mark.skipif(
    not (OUT / "long_chapters_sun_eater.jsonl").exists(),
    reason="Sun Eater long chapter has not been generated in this checkout",
)
def test_generated_sun_eater_long_chapter_is_chunkable():
    rows = [json.loads(line) for line in (OUT / "long_chapters_sun_eater.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert 3000 <= row["word_count"] <= 5500
    assert row["reference_pt"]
    assert 10 <= len(row["expected_terms"]) <= 40
    assert all(term["target"] for term in row["expected_terms"])

