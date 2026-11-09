"""Tests for the benchmark corpus loader."""
from __future__ import annotations

import json
from pathlib import Path

from benchmark.literary.corpus import load_corpus


def test_load_corpus_ignores_eval_metadata_fields(tmp_path: Path):
    path = tmp_path / "corpus.jsonl"
    row = {
        "id": "ex-1",
        "book": "Book",
        "author": "Author",
        "chapter_href": "OEBPS/ch1.xhtml",
        "category": "dialogue",
        "text": "A source paragraph.",
        "source_language": "en",
        "reference_pt": "Um parágrafo fonte.",
        "notes": "aligned",
        "book_slug": "book",
        "split": "dev",
        "alignment": {"en_href": "OEBPS/ch1.xhtml", "score": 9.0},
        "word_count": 4,
        "expected_terms": [{"source": "Book", "target": "Livro"}],
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    rows = load_corpus(str(path))

    assert len(rows) == 1
    assert rows[0].id == "ex-1"
    assert rows[0].chapter_href == "OEBPS/ch1.xhtml"
    assert rows[0].reference_pt == "Um parágrafo fonte."
