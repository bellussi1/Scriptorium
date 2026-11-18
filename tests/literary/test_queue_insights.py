"""Tests for the read-only queue insights used by the Queue UI."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from src.literary.queue_insights import (
    epub_metrics,
    find_log,
    kindle_zip,
    quality_payload,
    quality_sidecar_path,
    read_budget_summary,
    tail_lines,
)
from src.literary.reading_repair import convert_dialogue_quotes, merge_split_paragraphs
from src.literary.repair import _hygiene_fix_html_structure

from .conftest import make_epub


def test_find_log_prefers_the_run_directory(tmp_path: Path):
    run_dir = tmp_path / "runs"
    pilot_dir = tmp_path / "pilots"
    run_dir.mkdir()
    pilot_dir.mkdir(parents=True)
    (run_dir / "howling-dark.log").write_text("run", encoding="utf-8")
    (pilot_dir / "howling-dark-old.log").write_text("pilot", encoding="utf-8")

    assert find_log("Howling Dark", run_dir, pilot_dir) == run_dir / "howling-dark.log"


def test_find_log_falls_back_to_the_pilot_directory(tmp_path: Path):
    pilot_dir = tmp_path / "pilots" / "sun-eater"
    pilot_dir.mkdir(parents=True)
    log = pilot_dir / "howling-dark-full.log"
    log.write_text("pilot", encoding="utf-8")

    assert find_log("Howling Dark", tmp_path / "runs", tmp_path / "pilots") == log


def test_tail_lines_limits_and_handles_missing_files(tmp_path: Path):
    path = tmp_path / "book.log"
    path.write_text("\n".join(f"line {index}" for index in range(10)), encoding="utf-8")

    assert tail_lines(path, 3) == ["line 7", "line 8", "line 9"]
    assert tail_lines(tmp_path / "missing.log", 3) == []


def test_epub_metrics_reads_the_artifact(tmp_path: Path):
    path = make_epub(tmp_path / "book.epub", title="Metrics Book")

    metrics = epub_metrics(path)

    assert metrics["metrics"]["words"] > 0
    assert metrics["metrics"]["chapters"] == 2
    assert metrics["metrics"]["paragraphs"] == 3
    assert metrics["metrics"]["brackets"] == 0
    assert metrics["metrics"]["forbidden_forms"] == 0
    assert not metrics["quality_flags"]


def test_quality_payload_includes_artifact_report_and_log(tmp_path: Path):
    artifact = make_epub(tmp_path / "Howling Dark (pt-BR).refined.epub", title="Howling Dark")
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    (run_dir / "howling-dark.log").write_text("first\nlast line", encoding="utf-8")
    (run_dir / "howling-dark.report.json").write_text(
        json.dumps(
            {
                "validation": {"passed": True, "blocking": 0, "warnings": 2},
                "epubcheck": {"fatals": 0, "errors": 0, "warnings": 0},
                "refine": {"accepted": 4, "rejected": 1, "flagged": 5},
            }
        ),
        encoding="utf-8",
    )
    artifact_info = {
        "filename": artifact.name,
        "kind": "refined",
        "size": artifact.stat().st_size,
        "path": artifact,
    }
    book = {
        "id": 10,
        "title": "Howling Dark",
        "author": "Christopher Ruocchio",
        "series": "The Sun Eater",
        "series_index": 2.0,
        "status": "completed",
    }

    payload = quality_payload(book, artifact_info, run_dir=run_dir, pilot_dir=tmp_path / "pilots")

    assert payload["book"]["title"] == "Howling Dark"
    assert payload["artifact"]["kind"] == "refined"
    assert payload["metrics"]["words"] > 0
    assert payload["report"]["validation"]["passed"] is True
    assert payload["report"]["epubcheck"]["errors"] == 0
    assert payload["log"]["lines"][-1] == "last line"


def test_kindle_zip_keeps_the_folder_structure(tmp_path: Path):
    folder = tmp_path / "kindle"
    book = folder / "Author" / "Series" / "01 - Book (pt-BR).epub"
    book.parent.mkdir(parents=True)
    book.write_bytes(b"epub")
    (folder / "manifest.csv").write_text("book", encoding="utf-8")

    buffer = kindle_zip(folder)

    with zipfile.ZipFile(buffer) as archive:
        assert "Author/Series/01 - Book (pt-BR).epub" in archive.namelist()
        assert "manifest.csv" in archive.namelist()

def test_tail_lines_can_skip_sync_noise(tmp_path: Path):
    path = tmp_path / "book.log"
    path.write_text("translated chunk 1\n[10:00] sync: checked=2 matched=1 updated=0\ntranslated chunk 2", encoding="utf-8")

    assert tail_lines(path, 5, skip_sync=True) == ["translated chunk 1", "translated chunk 2"]

def test_quality_payload_reads_the_sidecar_without_a_queue_report(tmp_path: Path):
    artifact = make_epub(tmp_path / "Howling Dark (pt-BR).refined.epub", title="Howling Dark")
    sidecar = quality_sidecar_path(artifact)
    sidecar.write_text(
        json.dumps(
            {
                "epubcheck": {"fatals": 0, "errors": 0, "warnings": 0},
                "reader_repair": {"accepted": True, "merged": 7, "quote_paragraphs": 3},
            }
        ),
        encoding="utf-8",
    )
    book = {"id": 10, "title": "Howling Dark", "status": "completed"}
    artifact_info = {
        "filename": artifact.name,
        "kind": "refined",
        "size": artifact.stat().st_size,
        "path": artifact,
    }

    payload = quality_payload(book, artifact_info, run_dir=tmp_path / "runs", pilot_dir=tmp_path / "pilots")

    assert payload["epubcheck"]["errors"] == 0
    assert payload["report"]["reader_repair"]["merged"] == 7


def test_epub_metrics_reports_pt_pt_and_review_samples(tmp_path: Path, monkeypatch):
    compiled_dir = tmp_path / "compiled"
    compiled_dir.mkdir()
    (compiled_dir / "ship-of-magic-glossary.json").write_text(
        json.dumps(
            {
                "terms": [
                    {"source": "Liveship", "target": "Liveship", "forbidden": ["navio vivo"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.literary.queue_insights.DEFAULT_COMPILED_DIR", compiled_dir)
    path = make_epub(
        tmp_path / "Ship of Magic (pt-BR).refined.epub",
        title="Ship of Magic",
        language="pt-BR",
        chapters=[
            "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Capitulo 1</h1><p>De facto, o navio vivo entrou em contacto.</p></body></html>",
            "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Capitulo 2</h1><p>Tudo tranquilo aqui.</p></body></html>",
        ],
    )

    result = epub_metrics(path, title="Ship of Magic")

    assert result["metrics"]["pt_pt_blocking"] == 2
    assert result["metrics"]["pt_pt_total"] >= 2
    assert result["metrics"]["forbidden_forms"] >= 1
    assert "pt_pt_blocking_remaining" in result["quality_flags"]
    assert "forbidden_forms_remaining" in result["quality_flags"]
    assert any(hit["form"] == "navio vivo" and hit["count"] == 1 for hit in result["forbidden_hits"])
    assert any(sample["kind"] == "forbidden" and sample["match"] == "navio vivo" for sample in result["review_samples"])
    assert any(sample["kind"] == "pt_pt_blocking" and sample["href"] == "ch1.xhtml" for sample in result["review_samples"])


def test_read_budget_summary_calibrates_usd_and_brl(tmp_path: Path):
    budgets_file = tmp_path / "budgets.json"
    budgets_file.write_text(
        json.dumps(
            {
                "gemini": {
                    "currency": "USD",
                    "usd_to_brl": 5.75,
                    "cap_usd": 45.0,
                    "rate_per_m_words_uncached": 13.02,
                    "rate_per_m_words_optimized": 10.80,
                }
            }
        ),
        encoding="utf-8",
    )
    books = [
        {"id": 1, "provider": "gemini", "state": "completed", "word_count": 300_000, "estimated_cost": 2.76, "priority": 30},
        {"id": 6, "provider": "gemini", "state": "translating", "word_count": 260_000, "estimated_cost": 2.30, "priority": 25},
        {"id": 5, "provider": "gemini", "state": "pending", "word_count": 300_000, "estimated_cost": 2.76, "priority": 24},
        {"id": 99, "provider": "gemini", "state": "pending", "word_count": 0, "estimated_cost": 1.25, "priority": 10},
    ]

    summary = read_budget_summary(books, budgets_path=budgets_file)

    assert summary["completed_usd"] == 3.91
    assert summary["active_usd"] == 3.39
    assert summary["core_remaining_usd"] == 3.24
    assert summary["total_remaining_usd"] == 4.49
    assert summary["remaining_cap_usd"] == 37.7
    assert summary["usd_to_brl"] == 5.75
    assert summary["completed_brl"] == round(3.91 * 5.75, 2)
    assert summary["active_brl"] == round(3.39 * 5.75, 2)
    assert summary["core_remaining_brl"] == round(3.24 * 5.75, 2)
    assert summary["total_remaining_brl"] == round(4.49 * 5.75, 2)
    assert summary["cap_brl"] == round(45.0 * 5.75, 2)
    assert summary["remaining_cap_brl"] == round(37.7 * 5.75, 2)


def test_hygiene_fix_unwraps_nested_ceps_paragraph():
    raw = (
        '<p class="ceps">— <small class="calibre5">DE “<small class="calibre5">'
        'VIAGENS</small>”,</small>\n\n'
        '<p class="cotx">DE WINFRODA</p><small class="calibre5"/>Fiz meu caminho.</p>'
    )
    fixed, changes = _hygiene_fix_html_structure(raw)

    assert changes == 1
    assert '</small> <small class="calibre5">DE WINFRODA</small></p>' in fixed
    assert '\n\n<p class="cotx">Fiz meu caminho.</p>' in fixed


def test_reading_repair_preserves_bantam_ceps_epigraph_attribution():
    raw = (
        '<p class="ceps">— <small class="calibre5">“A CONSPIRAÇÃO DOS MALHADOS”, '
        'DE ROWELL</small></p>\n\n'
        '<p class="cotx">A guarda havia mudado.</p>'
    )
    merged_html, merged = merge_split_paragraphs(raw)
    quoted_html, quotes = convert_dialogue_quotes(merged_html)

    assert merged == 0
    assert quotes == 0
    assert '<p class="ceps">— <small class="calibre5">“A CONSPIRAÇÃO DOS MALHADOS”, DE ROWELL</small></p>' in quoted_html
    assert '<p class="cotx">A guarda havia mudado.</p>' in quoted_html
