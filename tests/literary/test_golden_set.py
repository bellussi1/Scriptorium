"""Golden set built from the real defects in Howling Dark and Demon in White.

Each fixture carries the broken text, the corrected text, the chapter and the
glossary term the rule needs. The broken file must fail the rule; the corrected
file must pass it.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from src.literary.per_file_audit import scan_book

FIXTURES = Path(__file__).parent / "fixtures" / "golden"


def _meta(name: str) -> dict:
    return json.loads((FIXTURES / name / "meta.json").read_text(encoding="utf-8"))


def _epub(path: Path, archive_name: str, content: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(archive_name, content)
    return path


def _scan(name: str, variant: str, tmp_path: Path) -> dict:
    meta = _meta(name)
    folder = FIXTURES / name
    source = _epub(
        tmp_path / f"{name}-source.epub",
        meta["file"],
        (folder / "source.xhtml").read_text(encoding="utf-8"),
    )
    target = _epub(
        tmp_path / f"{name}-{variant}.epub",
        meta["file"],
        (folder / f"{variant}.xhtml").read_text(encoding="utf-8"),
    )
    return scan_book(source, target, meta["terms"])


@pytest.mark.parametrize("name", ["caron_ch24", "vesperad_ch58"])
def test_truncated_term_fails_old_text_and_passes_new(name: str, tmp_path: Path):
    meta = _meta(name)
    broken = _scan(name, "broken", tmp_path)
    fixed = _scan(name, "fixed", tmp_path)

    assert meta["rule"] == "truncated_term"
    assert broken["gate"]["passed"] is False
    assert any("truncated term" in reason for reason in broken["gate"]["reasons"])
    truncated = broken["offenders"]["truncated"]
    assert truncated and truncated[0]["file"] == meta["file"]
    assert fixed["gate"]["passed"] is True, fixed["gate"]["reasons"]


@pytest.mark.parametrize("name", ["chantry_ch76", "vesperad_keep"])
def test_forbidden_rendering_fails_old_text_and_passes_new(name: str, tmp_path: Path):
    meta = _meta(name)
    broken = _scan(name, "broken", tmp_path)
    fixed = _scan(name, "fixed", tmp_path)

    assert meta["rule"] == "forbidden_rendering"
    assert broken["gate"]["passed"] is False
    assert any("forbidden" in reason for reason in broken["gate"]["reasons"])
    assert broken["totals"]["forbidden_hits"] >= 1
    assert fixed["gate"]["passed"] is True, fixed["gate"]["reasons"]


@pytest.mark.parametrize(
    "name", sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())
)
def test_fixture_references_chapter_and_rule(name: str):
    meta = _meta(name)

    assert meta["book"]
    assert meta["chapter"] > 0
    assert meta["rule"]
    assert meta["file"].startswith("OEBPS/")
    assert meta["expected"]
    assert (FIXTURES / name / "source.xhtml").exists()
    assert (FIXTURES / name / "broken.xhtml").exists()
    assert (FIXTURES / name / "fixed.xhtml").exists()
