"""Post-pass for finished EPUBs: localised chapter titles and exact text edits.

Books translated before the chapter-title step keep the English titles in the
chapter ``<title>`` elements, the table of contents and the NCX. This module
applies a reviewed title map (YAML, kept under ``literary-resources``) and
optional exact-match text edits. It never guesses: the title map must match
the EPUB chapter for chapter, and each edit must match exactly once.

The command gates the result the way the queue runner does. The pair
validation and EPUBCheck must pass before the file is replaced.

Run from the repository root::

    python -m src.literary.chapter_titles \\
        --source-en "<English EPUB>" \\
        --epub "translated_files/Demon in White (pt-BR).refined.epub" \\
        --titles literary-resources/christopher-ruocchio/sun-eater/chapter-titles/demon-in-white.yaml \\
        --edit "OEBPS/xhtml/96_Lexicon.xhtml|<b>Chantry</b>|<b>Chantria</b>"
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

import yaml

TITLE_ELEMENT = re.compile(r"<title>(.*?)</title>", re.DOTALL)
CHAPTER_TITLE = re.compile(r"^Chapter (\d+): (.+)$", re.DOTALL)
TOC_NAV = re.compile(r'<nav\b[^>]*epub:type="toc"[^>]*>.*?</nav>', re.DOTALL)
NAV_LINK = re.compile(r'(<a\b[^>]*?href="([^"]+)"[^>]*>)(.*?)(</a>)', re.DOTALL)
NCX_MAP = re.compile(r"<navMap\b.*?</navMap>", re.DOTALL)
NCX_POINT_LABEL = re.compile(
    r'(<navLabel>\s*<text>)(.*?)(</text>\s*</navLabel>\s*<content\s+src="([^"]+)"\s*/>)',
    re.DOTALL,
)


def _norm(value: str) -> str:
    """Compare titles with ASCII apostrophes and no surrounding spaces."""
    return value.replace("’", "'").replace("‘", "'").strip()


def load_title_map(path: str | Path) -> Dict[str, Any]:
    """Read a title map and return ``{"book": str, "series": str, "series_index": float, "chapters": {n: {en, pt}}}``."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML value must be a mapping")
    chapters: Dict[int, Dict[str, str]] = {}
    for item in data.get("chapters") or []:
        number = int(item["number"])
        if number in chapters:
            raise ValueError(f"{path}: chapter {number} appears twice")
        chapters[number] = {"en": str(item["en"]), "pt": str(item["pt"])}
    if not chapters:
        raise ValueError(f"{path}: no chapters listed")
    return {
        "book": str(data.get("book") or ""),
        "series": str(data.get("series") or ""),
        "series_index": float(data["series_index"]) if data.get("series_index") is not None else None,
        "chapters": chapters,
    }


def _find_chapters(content: Dict[str, bytes], book: str) -> Dict[int, Tuple[str, str]]:
    """Map chapter number -> (member name, English title) from the chapter ``<title>`` elements."""
    found: Dict[int, Tuple[str, str]] = {}
    for name, raw in content.items():
        if not name.lower().endswith((".xhtml", ".html")):
            continue
        match = TITLE_ELEMENT.search(raw.decode("utf-8", "replace"))
        if not match:
            continue
        chapter = CHAPTER_TITLE.match(html.unescape(match.group(1)).strip())
        if not chapter:
            continue
        english = chapter.group(2)
        suffix = f", {book}"
        if book and english.endswith(suffix):
            english = english[: -len(suffix)]
        number = int(chapter.group(1))
        if number in found:
            raise ValueError(f"chapter {number} appears in two files: {found[number][0]} and {name}")
        found[number] = (name, english)
    return found


def _retitle_toc(text: str, labels: Dict[str, str]) -> Tuple[str, int]:
    """Set the label of each TOC link whose file name is in ``labels``; page-list links are not touched."""
    changed = 0

    def replace_block(block_match: "re.Match[str]") -> str:
        nonlocal changed

        def replace_link(link: "re.Match[str]") -> str:
            nonlocal changed
            target = os.path.basename(link.group(2).split("#", 1)[0])
            if target not in labels:
                return link.group(0)
            changed += 1
            return f"{link.group(1)}{escape(labels[target])}{link.group(4)}"

        return NAV_LINK.sub(replace_link, block_match.group(0))

    return TOC_NAV.sub(replace_block, text), changed


def _retitle_ncx(text: str, labels: Dict[str, str]) -> Tuple[str, int]:
    """Set the navLabel of each navPoint in ``navMap`` whose content file is in ``labels``."""
    changed = 0

    def replace_map(map_match: "re.Match[str]") -> str:
        nonlocal changed

        def replace_point(point: "re.Match[str]") -> str:
            nonlocal changed
            target = os.path.basename(point.group(4).split("#", 1)[0])
            if target not in labels:
                return point.group(0)
            changed += 1
            return f"{point.group(1)}{escape(labels[target])}{point.group(3)}"

        return NCX_POINT_LABEL.sub(replace_point, map_match.group(0))

    return NCX_MAP.sub(replace_map, text), changed


def apply_epub_edits(
    source: str | Path,
    output: str | Path,
    *,
    titles: Optional[Dict[str, Any]] = None,
    edits: Sequence[Tuple[str, str, str]] = (),
) -> Dict[str, Any]:
    """Write ``output`` from ``source`` with the title map and exact edits applied.

    Raises ``ValueError`` before writing anything when the title map does not
    match the EPUB or an edit does not match exactly once.
    """
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        content = {info.filename: archive.read(info.filename) for info in infos}

    changed: Dict[str, bytes] = {}
    report: Dict[str, Any] = {"chapters_retitled": 0, "toc_labels": 0, "ncx_labels": 0, "text_edits": []}

    if titles is not None:
        mapping: Dict[int, Dict[str, str]] = titles["chapters"]
        found = _find_chapters(content, titles["book"])
        missing = sorted(set(mapping) - set(found))
        extra = sorted(set(found) - set(mapping))
        mismatch = [
            (number, found[number][1], mapping[number]["en"])
            for number in sorted(set(found) & set(mapping))
            if _norm(found[number][1]) != _norm(mapping[number]["en"])
        ]
        if missing or extra or mismatch:
            raise ValueError(
                f"title map does not match the EPUB: missing={missing} extra={extra} mismatch={mismatch}"
            )

        labels: Dict[str, str] = {}
        for number, (name, _english) in sorted(found.items()):
            label = f"Capítulo {number}: {mapping[number]['pt']}"
            text = changed.get(name, content[name]).decode("utf-8")
            text, count = TITLE_ELEMENT.subn(f"<title>{escape(label)}</title>", text, count=1)
            if count != 1:
                raise ValueError(f"{name}: no <title> element to replace")
            changed[name] = text.encode("utf-8")
            labels[os.path.basename(name)] = label
            report["chapters_retitled"] += 1

        for name in content:
            if name.lower().endswith((".xhtml", ".html")):
                text = changed.get(name, content[name]).decode("utf-8")
                if TOC_NAV.search(text):
                    text, count = _retitle_toc(text, labels)
                    report["toc_labels"] += count
                    changed[name] = text.encode("utf-8")
            elif name.lower().endswith(".ncx"):
                text = changed.get(name, content[name]).decode("utf-8")
                text, count = _retitle_ncx(text, labels)
                report["ncx_labels"] += count
                changed[name] = text.encode("utf-8")

    for member, old, new in edits:
        matches = [name for name in content if name == member or name.endswith("/" + member)]
        if len(matches) != 1:
            raise ValueError(f"edit target {member!r} matched {len(matches)} files")
        name = matches[0]
        text = changed.get(name, content[name]).decode("utf-8")
        count = text.count(old)
        if count != 1:
            raise ValueError(f"{name}: expected exactly one occurrence of {old!r}, found {count}")
        changed[name] = text.replace(old, new, 1).encode("utf-8")
        report["text_edits"].append({"file": name, "old": old, "new": new})

    with zipfile.ZipFile(output, "w") as out:
        for info in infos:
            data = changed.get(info.filename, content[info.filename])
            compress = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            out.writestr(zipfile.ZipInfo(info.filename, date_time=info.date_time), data, compress_type=compress)
    return report


def _parse_edit(value: str) -> Tuple[str, str, str]:
    parts = value.split("|")
    if len(parts) != 3 or not parts[0] or not parts[1]:
        raise argparse.ArgumentTypeError("edit must be MEMBER|OLD|NEW with a non-empty member and OLD")
    return parts[0], parts[1], parts[2]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--epub", required=True, type=Path, help="translated EPUB to update in place")
    parser.add_argument("--source-en", required=True, type=Path, help="English source EPUB for pair validation")
    parser.add_argument("--titles", type=Path, help="chapter title map (YAML)")
    parser.add_argument("--edit", type=_parse_edit, action="append", default=[], help="MEMBER|OLD|NEW exact edit")
    parser.add_argument("--series-metadata", action="store_true", help="write series metadata from the title map")
    args = parser.parse_args(argv)

    from .epub import update_opf_metadata
    from .queue_runner import _epubcheck
    from .validation import validate_epub_pair

    titles = load_title_map(args.titles) if args.titles else None
    stage = args.epub.with_name(f".{args.epub.stem}.post.tmp.epub")
    try:
        report = apply_epub_edits(args.epub, stage, titles=titles, edits=args.edit)
        if args.series_metadata:
            if titles is None or not titles["series"] or titles["series_index"] is None:
                raise ValueError("--series-metadata needs series and series_index in the title map")
            series_stage = stage.with_name(f".{args.epub.stem}.series.tmp.epub")
            update_opf_metadata(
                str(stage), str(series_stage), series=titles["series"], series_index=titles["series_index"]
            )
            os.replace(series_stage, stage)
            report["series_metadata"] = {"series": titles["series"], "series_index": titles["series_index"]}
        validation = validate_epub_pair(str(args.source_en), str(stage), expected_language="pt-BR")
        epubcheck = _epubcheck(stage)
        passed = bool(validation.get("passed")) and epubcheck.get("errors") == 0
        report["gate"] = {"passed": passed, "pair_passed": bool(validation.get("passed")), "epubcheck_errors": epubcheck.get("errors")}
        if passed:
            os.replace(stage, args.epub)
        else:
            report["gate"]["kept"] = "original unchanged"
    finally:
        if stage.exists():
            stage.unlink()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
