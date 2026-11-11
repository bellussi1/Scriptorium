"""Tests for the audit sample alignment."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("audit_book", ROOT / "scripts" / "audit_book.py")
assert SPEC and SPEC.loader
audit_book = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_book)


def test_alignment_handles_a_split_paragraph():
    source = [8, 39, 83, 62, 18, 110, 115, 101]
    target = [6, 34, 23, 69, 63, 20, 113, 105, 49, 60]
    mapping = audit_book._align_paragraphs(source, target)

    assert mapping[1] == (1, 2)
    assert mapping[2] == (2, 4)
    assert mapping[3] == (4, 5)
    assert mapping[4] == (5, 6)
    assert mapping[5] == (6, 7)


def test_alignment_handles_a_merge_and_a_trailing_extra():
    source = [50, 60, 70, 80]
    target = [115, 72, 81, 20]
    mapping = audit_book._align_paragraphs(source, target)

    assert mapping[0] == (0, 1)
    assert mapping[1] == (0, 1)
    assert mapping[2] == (1, 2)
    assert mapping[3] == (2, 4)


def test_sample_pairs_uses_the_aligned_passage():
    source = [
        ("OEBPS/ch1.xhtml", ["Chapter One"] + [f"source paragraph {i} " * 50 for i in range(1, 8)]),
    ]
    target = [
        (
            "OEBPS/ch1.xhtml",
            ["Capítulo Um"]
            + [f"parágrafo traduzido {i} " * 25 for i in range(1, 15)],
        ),
    ]
    samples = audit_book._sample_pairs(source, target, limit=1)

    assert len(samples) == 1
    sample = samples[0]
    assert sample["id"] == "OEBPS/ch1.xhtml:1"
    assert sample["target"].startswith("parágrafo traduzido 1")
    assert "parágrafo traduzido 2" in sample["target"]
