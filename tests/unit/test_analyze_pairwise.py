"""Tests for the blind pairwise analyzer's A/B normalization."""
from __future__ import annotations

from scripts.analyze_pairwise import _merge_metadata, analyze


def _row(item_id: str, score_a, score_b, preference: str, book: str = "Book") -> dict:
    return {
        "id": item_id,
        "book": book,
        "category": "dialogue",
        "score_a": score_a,
        "score_b": score_b,
        "preference": preference,
    }


def test_key_normalizes_per_row_swaps_to_one_reference_model():
    rows = [
        _row("1", 5, 3, "a"),
        _row("2", 5, 2, "a"),
        _row("3", 3, 3, "tie"),
        _row("4", 1, 4, "b"),
    ]
    key = {
        "1": {"a": "index", "b": "q4"},
        "2": {"a": "q4", "b": "index"},
        "3": {"a": "index", "b": "q4"},
        "4": {"a": "q4", "b": "index"},
    }

    result = analyze(rows, key=key, reference_model="index")

    assert result["model_a"] == "index"
    assert result["model_b"] == "q4"
    assert result["wins_a"] == 2
    assert result["wins_b"] == 1
    assert result["ties"] == 1
    assert result["mean_diff_a_minus_b"] == 0.5
    assert result["sign_test_p"] is not None


def test_rows_without_key_mapping_are_rejected():
    rows = [_row("missing", 4, 2, "a")]
    key = {"other": {"a": "index", "b": "q4"}}

    try:
        analyze(rows, key=key, reference_model="index")
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected a missing-key ValueError")


def test_empty_preference_falls_back_to_scores():
    rows = [_row("1", 4, 2, "")]
    key = {"1": {"a": "index", "b": "q4"}}

    result = analyze(rows, key=key, reference_model="index")

    assert result["wins_a"] == 1
    assert result["wins_b"] == 0


def test_sheet_metadata_is_merged_into_judgments():
    rows = [{"id": "1", "score_a": 4, "score_b": 3, "preference": "a"}]
    sheet = [{"id": "1", "book": "Empire of Silence", "category": "dialogue"}]

    merged = _merge_metadata(rows, sheet)

    assert merged[0]["book"] == "Empire of Silence"
    assert merged[0]["category"] == "dialogue"
    assert merged[0]["preference"] == "a"


def test_bootstrap_by_book_reports_cluster_count():
    rows = [
        _row("1", 5, 3, "a", book="A"),
        _row("2", 4, 2, "a", book="A"),
        _row("3", 2, 4, "b", book="B"),
        _row("4", 3, 3, "tie", book="B"),
    ]
    key = {
        "1": {"a": "index", "b": "q4"},
        "2": {"a": "index", "b": "q4"},
        "3": {"a": "index", "b": "q4"},
        "4": {"a": "index", "b": "q4"},
    }

    result = analyze(rows, key=key, reference_model="index")

    assert result["bootstrap_by_book"]["clusters"] == 2
    assert result["bootstrap"]["clusters"] == 4
