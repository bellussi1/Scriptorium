"""Tests for the read-only queue insights used by the Queue UI."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from src.literary.metadata import standardized_title
from src.literary.models import BookRecord
from src.literary.queue import QueueStore
from src.literary.queue_insights import (
    check_cloud_budget_gate,
    epub_metrics,
    find_log,
    kindle_zip,
    quality_payload,
    quality_sidecar_path,
    read_budget_summary,
    tail_lines,
)
from src.literary.reading_repair import convert_dialogue_quotes, merge_split_paragraphs
from src.literary.repair import (
    _hygiene_fix_bloated_ncx_labels,
    _hygiene_fix_html_structure,
)

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
                    "cap_usd": 40.0,
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
    assert summary["cap_usd"] == 40.0
    assert summary["remaining_cap_usd"] == 32.7
    assert summary["usd_to_brl"] == 5.75
    assert summary["completed_brl"] == round(3.91 * 5.75, 2)
    assert summary["active_brl"] == round(3.39 * 5.75, 2)
    assert summary["core_remaining_brl"] == round(3.24 * 5.75, 2)
    assert summary["total_remaining_brl"] == round(4.49 * 5.75, 2)
    assert summary["cap_brl"] == round(40.0 * 5.75, 2)
    assert summary["remaining_cap_brl"] == round(32.7 * 5.75, 2)


def test_check_cloud_budget_gate_blocks_when_next_book_exceeds_40_usd_cap(tmp_path: Path):
    db_file = tmp_path / "literary_queue.db"
    budgets_file = tmp_path / "budgets.json"
    budgets_file.write_text(
        json.dumps(
            {
                "gemini": {
                    "currency": "USD",
                    "usd_to_brl": 5.75,
                    "cap_usd": 40.0,
                    "rate_per_m_words_uncached": 13.02,
                    "rate_per_m_words_optimized": 10.80,
                }
            }
        ),
        encoding="utf-8",
    )
    store = QueueStore(str(db_file))
    try:
        done_id = store.add_book(
            BookRecord(calibre_id=1, title="Done Book", epub_path=str(tmp_path / "done.epub"), word_count=300_000),
            provider="gemini",
            model="gemini-3.8-flash",
        )
        with store._connect() as conn:
            conn.execute(
                "UPDATE books SET status = 'completed', actual_cost = ? WHERE id = ?",
                (37.0, done_id),
            )
            conn.commit()
        fits_id = store.add_book(
            BookRecord(calibre_id=2, title="Fits Cap", epub_path=str(tmp_path / "fits.epub"), word_count=200_000),
            provider="gemini",
            model="gemini-3.8-flash",
        )
        over_id = store.add_book(
            BookRecord(calibre_id=3, title="Exceeds Cap", epub_path=str(tmp_path / "over.epub"), word_count=250_000),
            provider="gemini",
            model="gemini-3.8-flash",
        )
        local_id = store.add_book(
            BookRecord(calibre_id=4, title="Local Ollama", epub_path=str(tmp_path / "local.epub"), word_count=500_000),
            provider="ollama",
            model="hy-mt2-7b",
        )
        fits_book = store.get_book(fits_id)
        over_book = store.get_book(over_id)
        local_book = store.get_book(local_id)
    finally:
        store.close()

    assert check_cloud_budget_gate(fits_book, db_file, budgets_path=budgets_file)["allowed"] is True
    blocked = check_cloud_budget_gate(over_book, db_file, budgets_path=budgets_file)
    assert blocked["allowed"] is False
    assert blocked["cap_usd"] == 40.0
    assert blocked["projected_usd"] > 40.0
    assert check_cloud_budget_gate(local_book, db_file, budgets_path=budgets_file)["allowed"] is True


def test_hygiene_fix_bloated_ncx_labels_and_hobb_title():
    ncx = (
        '<ncx><navMap>'
        '<navPoint id="n1" playOrder="1"><navLabel><text>'
        + ("capítulo 1 LAGARTOS " + ("Texto longo. " * 20))
        + '</text></navLabel><content src="Text/ch1.htm#c01"/></navPoint>'
        '</navMap></ncx>'
    )
    texts = {
        "Text/ch1.htm": '<p class="cn"><em>capítulo</em> 1</p><p class="ct">NO REINO DA MULHER PÁLIDA</p>',
    }
    updated, count = _hygiene_fix_bloated_ncx_labels(ncx, "toc.ncx", texts)
    assert count == 1
    assert "<text>Capítulo 1 — No Reino da Mulher Pálida</text>" in updated

    hobb = SimpleNamespace(title="Fool's Fate", author="Robin Hobb")
    assert standardized_title(hobb, "O Destino do Bufão") == "O Destino do Bobo"


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


def test_hygiene_fixes_html_extension_mismatch_and_missing_css_font_face(tmp_path):
    import zipfile

    from src.literary.repair import repair_epubcheck_hygiene_in_epub

    src_epub = tmp_path / "broken.epub"
    out_epub = tmp_path / "fixed.epub"
    with zipfile.ZipFile(src_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("OEBPS/Text/titlepage.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body/></html>')
        zf.writestr(
            "OEBPS/Text/part0007.html",
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><a href="../Text/titlepage.html">Capa</a></body></html>',
        )
        zf.writestr("OEBPS/Fonts/00001.ttf", b"fakefont")
        zf.writestr(
            "OEBPS/Styles/page_styles.css",
            "@font-face { font-family: 'Charis'; src: url(styles/XXXXXXXXXXXXXXXX); }\n"
            "@font-face { font-family: 'Charis'; src: url(../Fonts/00001.ttf); }\n",
        )

    res = repair_epubcheck_hygiene_in_epub(str(src_epub), str(out_epub))
    assert res["total_changes"] == 2
    with zipfile.ZipFile(out_epub, "r") as zf:
        part7 = zf.read("OEBPS/Text/part0007.html").decode("utf-8")
        css = zf.read("OEBPS/Styles/page_styles.css").decode("utf-8")
    assert '../Text/titlepage.xhtml' in part7
    assert "XXXXXXXXXXXXXXXX" not in css
    assert "../Fonts/00001.ttf" in css


def test_read_book_quality_summaries_reads_artefact_changes_splits(tmp_path):
    import json

    from src.literary.queue_insights import read_book_quality_summaries

    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    (run_dir / "fool-s-assassin.report.json").write_text(
        json.dumps(
            {
                "gate_passed": True,
                "epubcheck": {"fatals": 0, "errors": 0, "warnings": 0},
                "reader_repair": {
                    "merged": 72,
                    "artefact_changes": {"split_dialogue_paragraphs": 529},
                },
            }
        ),
        encoding="utf-8",
    )
    summaries = read_book_quality_summaries(
        [{"id": 16, "title": "Fool's Assassin", "status": "completed"}],
        run_dir=run_dir,
        pilot_dir=tmp_path / "pilot",
        audits_dir=tmp_path / "audits",
        kindle_dir=tmp_path / "kindle",
    )
    assert summaries["16"]["reader_merged"] == 72
    assert summaries["16"]["reader_splits"] == 529
