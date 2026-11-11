"""Tests for the per-file deterministic audit."""
from __future__ import annotations

import zipfile
from pathlib import Path

from src.literary.per_file_audit import scan_book


def _epub(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in files.items():
            archive.writestr(
                name,
                '<?xml version="1.0" encoding="utf-8"?>'
                f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>',
            )
    return path


def _term(
    source: str = "Chantry",
    target: str = "Chantria",
    forbidden: list[str] | None = None,
) -> dict:
    return {
        "source": source,
        "target": target,
        "forbidden": forbidden if forbidden is not None else ["Chantry"],
        "aliases": [],
    }


def _filler(words: int) -> str:
    syllables = ["ba", "ce", "di", "fo", "gu", "ja", "le", "mi", "no", "pu", "ra", "se", "ti", "vo", "xa", "ze"]
    tokens = []
    for index in range(words):
        first = syllables[index % len(syllables)]
        second = syllables[(index // len(syllables)) % len(syllables)]
        third = syllables[(index // (len(syllables) ** 2)) % len(syllables)]
        tokens.append(f"{first}{second}{third}{index}")
    return " ".join(tokens)


def test_inline_tags_do_not_hide_a_forbidden_term(tmp_path: Path):
    source = _epub(tmp_path / "source.epub", {"OEBPS/ch1.xhtml": "<p>The Chantry is old.</p>"})
    target = _epub(
        tmp_path / "target.epub",
        {"OEBPS/ch1.xhtml": "<p><span>C</span>HANTRY é o nome.</p>"},
    )

    report = scan_book(source, target, [_term()])

    assert report["gate"]["passed"] is False
    assert report["totals"]["forbidden_hits"] == 1
    assert report["files"][0]["forbidden"][0]["forbidden"] == "Chantry"


def test_short_blocks_are_scanned(tmp_path: Path):
    source = _epub(tmp_path / "source.epub", {"OEBPS/ch1.xhtml": "<p>The Chantry is old.</p>"})
    target = _epub(tmp_path / "target.epub", {"OEBPS/ch1.xhtml": "<p>CHANTRY</p>"})

    report = scan_book(source, target, [_term()])

    assert report["totals"]["forbidden_hits"] == 1
    assert report["totals"]["words"] == 1


def test_glossary_is_checked_per_file(tmp_path: Path):
    source = _epub(
        tmp_path / "source.epub",
        {
            "OEBPS/a.xhtml": "<p>The Chantry is old.</p>",
            "OEBPS/b.xhtml": "<p>The Chantry is new.</p>",
        },
    )
    target = _epub(
        tmp_path / "target.epub",
        {
            "OEBPS/a.xhtml": "<p>A Chantria é antiga.</p>",
            "OEBPS/b.xhtml": "<p>A Cantoria é nova.</p>",
        },
    )

    report = scan_book(source, target, [_term()])

    assert report["totals"]["glossary_pairs"] == 2
    assert report["totals"]["glossary_hits"] == 1
    assert report["totals"]["glossary_coverage"] == 0.5
    assert [item["file"] for item in report["offenders"]["glossary_missing"]] == [
        "OEBPS/b.xhtml"
    ]
    assert report["gate"]["passed"] is False


def test_pt_pt_cluster_fails_a_file_that_the_global_rate_would_hide(tmp_path: Path):
    clean = _filler(10_000)
    cluster = " ".join(["contacto"] * 5 + _filler(600).split())
    source = _epub(
        tmp_path / "source.epub",
        {"OEBPS/clean.xhtml": f"<p>{clean}</p>", "OEBPS/cluster.xhtml": f"<p>{cluster}</p>"},
    )
    target = _epub(
        tmp_path / "target.epub",
        {"OEBPS/clean.xhtml": f"<p>{clean}</p>", "OEBPS/cluster.xhtml": f"<p>{cluster}</p>"},
    )

    report = scan_book(source, target, [])

    assert report["totals"]["pt_pt_blocking"] == 5
    assert report["totals"]["pt_pt_blocking_per_100k"] < 50
    assert report["gate"]["passed"] is False
    assert any("pt-PT cluster" in reason for reason in report["gate"]["reasons"])
    cluster_file = next(item for item in report["files"] if item["name"] == "OEBPS/cluster.xhtml")
    assert cluster_file["pt_pt"]["blocking_per_100k"] > 100


def test_archaic_address_is_reported_but_not_blocking(tmp_path: Path):
    text = " ".join(["vós"] * 5 + _filler(600).split())
    source = _epub(tmp_path / "source.epub", {"OEBPS/ch1.xhtml": f"<p>{text}</p>"})
    target = _epub(tmp_path / "target.epub", {"OEBPS/ch1.xhtml": f"<p>{text}</p>"})

    report = scan_book(source, target, [])

    assert report["totals"]["pt_pt"] == 5
    assert report["totals"]["pt_pt_blocking"] == 0
    assert report["gate"]["passed"] is True


def test_length_ratio_outlier_is_flagged_per_file(tmp_path: Path):
    source_text = _filler(300)
    target_text = _filler(100)
    source = _epub(tmp_path / "source.epub", {"OEBPS/ch1.xhtml": f"<p>{source_text}</p>"})
    target = _epub(tmp_path / "target.epub", {"OEBPS/ch1.xhtml": f"<p>{target_text}</p>"})

    report = scan_book(source, target, [])

    assert report["gate"]["passed"] is False
    assert any("length ratio" in reason for reason in report["gate"]["reasons"])
    assert report["offenders"]["length_ratio"][0]["ratio"] < 0.8


def test_untranslated_all_caps_term_is_flagged(tmp_path: Path):
    source = _epub(tmp_path / "source.epub", {"OEBPS/ch1.xhtml": "<p>The Chantry is old.</p>"})
    target = _epub(tmp_path / "target.epub", {"OEBPS/ch1.xhtml": "<p>CHANTRY é o nome.</p>"})

    report = scan_book(source, target, [_term()])

    assert report["totals"]["caps_hits"] == 1
    assert any("untranslated all-caps" in reason for reason in report["gate"]["reasons"])


def test_dropcap_issue_is_flagged(tmp_path: Path):
    source = _epub(tmp_path / "source.epub", {"OEBPS/ch1.xhtml": "<p>The Chantry is old.</p>"})
    target = _epub(
        tmp_path / "target.epub",
        {"OEBPS/ch1.xhtml": '<p><span class="dropcap"></span>HANTRY é o nome.</p>'},
    )

    report = scan_book(source, target, [_term()])

    assert report["totals"]["dropcap_issues"] >= 1
    assert any("dropcap integrity" in reason for reason in report["gate"]["reasons"])


def test_clean_book_passes(tmp_path: Path):
    source = _epub(tmp_path / "source.epub", {"OEBPS/ch1.xhtml": "<p>The Chantry is old.</p>"})
    target = _epub(tmp_path / "target.epub", {"OEBPS/ch1.xhtml": "<p>A Chantria é antiga.</p>"})

    report = scan_book(source, target, [_term()])

    assert report["gate"]["passed"] is True
    assert report["totals"]["forbidden_hits"] == 0
    assert report["totals"]["glossary_coverage"] == 1.0
