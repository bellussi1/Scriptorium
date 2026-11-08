"""Tests for the anonymized benchmark review sheet."""
from __future__ import annotations

import json
from pathlib import Path

from benchmark.literary.runner import blind_report


def _corpus(path: Path) -> None:
    rows = [
        {
            "id": "book-1-0",
            "book": "Book One",
            "author": "Author",
            "chapter_href": "ch1.xhtml",
            "category": "dialogue",
            "text": "Source sentence one.",
            "source_language": "en",
            "reference_pt": "",
            "notes": "",
        },
        {
            "id": "book-1-1",
            "book": "Book One",
            "author": "Author",
            "chapter_href": "ch1.xhtml",
            "category": "narration",
            "text": "Source sentence two.",
            "source_language": "en",
            "reference_pt": "",
            "notes": "",
        },
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_blind_report_anonymizes_model_names(tmp_path: Path):
    corpus = tmp_path / "corpus.jsonl"
    _corpus(corpus)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    summary = {
        "corpus": str(corpus),
        "models": ["alpha-model", "beta-model"],
        "results": [
            {"id": "book-1-0", "model": "alpha-model", "generation": {"text": "Saída alpha."}},
            {"id": "book-1-0", "model": "beta-model", "generation": {"text": "Saída beta."}},
            {"id": "book-1-1", "model": "alpha-model", "generation": {"text": "Outra alpha."}},
            {"id": "book-1-1", "model": "beta-model", "generation": {"text": "Outra beta."}},
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    result = blind_report(str(run_dir))

    assert result["models"] == 2
    assert result["entries"] == 4
    review_text = Path(result["review"]).read_text(encoding="utf-8")
    assert "alpha-model" not in review_text
    assert "beta-model" not in review_text
    rows = [json.loads(line) for line in review_text.splitlines() if line.strip()]
    assert {row["label"] for row in rows} == {"A", "B"}
    assert rows[0]["source"] == "Source sentence one."

    key = json.loads(Path(result["key"]).read_text(encoding="utf-8"))
    assert key["labels"]["alpha-model"] == "A"
    assert key["labels"]["beta-model"] == "B"
