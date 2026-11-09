"""Tests for the read-only queue insights used by the Queue UI."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from src.literary.queue_insights import (
    epub_metrics,
    find_log,
    find_report,
    kindle_zip,
    quality_payload,
    quality_sidecar_path,
    tail_lines,
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
    assert metrics["metrics"]["chantry"] == 0
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
