from pathlib import Path

import pytest

from src.literary.cost import estimate_book, estimate_scenario
from src.literary.models import BookRecord, Severity
from src.literary.queue import QueueStore
from src.literary.validation import summarize_issues, validate_pair

from .conftest import make_epub


def _record(path: Path) -> BookRecord:
    return BookRecord(
        calibre_id=1,
        title="Test Book",
        author="Test Author",
        series="Test Series",
        series_index=1.0,
        languages=["en"],
        formats=["EPUB"],
        epub_path=str(path),
        word_count=100000,
        chapter_count=10,
    )


def test_queue_is_idempotent_and_records_chapters(tmp_path: Path):
    epub = make_epub(tmp_path / "book.epub")
    store = QueueStore(str(tmp_path / "queue.db"))
    record = _record(epub)
    first = store.add_book(record, model="deepseek-flash", provider="deepseek")
    second = store.add_book(record, model="deepseek-flash", provider="deepseek")
    assert first == second
    assert len(store.list_books()) == 1
    job = store.create_job(first, total_chapters=2)
    store.record_chapter(job, 0, href="ch1.xhtml", title="Chapter One", status="completed", tokens_in=100, tokens_out=95)
    chapters = store.list_chapters(job)
    assert len(chapters) == 1
    assert chapters[0].status == "completed"
    assert store.next_pending().id == first
    store.set_book_state(first, "preparing")
    store.set_book_state(first, "translating")
    with pytest.raises(ValueError):
        store.set_book_state(first, "pending")
    store.close()


def test_queue_orders_by_series_index(tmp_path: Path):
    epub = make_epub(tmp_path / "book.epub")
    store = QueueStore(str(tmp_path / "queue.db"))
    later = _record(epub)
    later.calibre_id = 2
    later.title = "Book Two"
    later.series_index = 2.0
    earlier = _record(epub)
    earlier.calibre_id = 1
    earlier.title = "Book One"
    earlier.series_index = 1.0
    store.add_book(later)
    store.add_book(earlier)
    assert store.next_pending().title == "Book One"
    store.close()


def test_queue_reset_marks_in_progress_paused(tmp_path: Path):
    epub = make_epub(tmp_path / "book.epub")
    store = QueueStore(str(tmp_path / "queue.db"))
    book_id = store.add_book(_record(epub))
    store.set_book_state(book_id, "preparing")
    assert store.reset_in_progress() == 1
    assert store.get_book(book_id).status == "paused"
    store.close()


def test_validation_flags_missing_paragraph_number_and_glossary():
    source = "Chapter One\n\nJohn rode for 3 days.\n\nHe reached Fort Smith."
    target = "Capítulo Um\n\nJohn cavalgou por três dias.\n\nChegou a Fort Smith."
    issues = validate_pair(source, target)
    codes = {issue.code for issue in issues}
    assert "target.numbers" in codes

    source2 = "John rode for 3 days.\n\nHe reached Fort Smith."
    target2 = "John cavalgou por 3 dias."
    issues2 = validate_pair(source2, target2)
    assert any(issue.code == "target.paragraphs" for issue in issues2)


def test_validation_glossary_and_forbidden(tmp_path: Path):
    from src.literary.resources import compile_for_book, load_tree

    root = tmp_path / "literary-resources"
    (root / "a" / "u").mkdir(parents=True)
    (root / "a" / "u" / "glossary.yaml").write_text(
        "terms:\n- source: Fitz\n  target: FitzChivalry\n  forbidden: [Fitz Chivalry]\n  confidence: confirmed\n",
        encoding="utf-8",
    )
    compiled = compile_for_book(load_tree(root), "a", "u")
    issues = validate_pair("Fitz spoke.", "Fitz Chivalry falou.", compiled=compiled)
    codes = {issue.code for issue in issues}
    assert "glossary.missing_target" in codes
    assert "glossary.forbidden" in codes
    summary = summarize_issues(issues)
    assert summary["passed"] is False


def test_cost_estimate_positive_and_cache_aware():
    estimate = estimate_book(word_count=100000, provider="deepseek", model="deepseek-flash")
    assert estimate.total_cost > 0
    assert estimate.input_tokens > 0
    assert estimate.output_tokens > 0
    assert estimate.assumptions["chunks"] > 0

    local = estimate_book(word_count=100000, provider="ollama", model="hy-mt2-7b")
    assert local.total_cost == 0

    batch = estimate_book(word_count=100000, provider="gemini", model="gemini-3.8-flash", batch=True)
    standard = estimate_book(word_count=100000, provider="gemini", model="gemini-3.8-flash")
    assert batch.total_cost < standard.total_cost


def test_scenario_hybrid_adds_selective_review():
    estimate = estimate_scenario(100000, "D")
    assert estimate["total_cost"] > 0
    assert estimate["selective_review"]["total_cost"] > 0
