"""Restore chapter headings in a finished EPUB whose body has none.

Some refined EPUBs were split by source file and never got chapter headings.
This module finds where each English chapter starts in the translated body,
inserts the house-style heading there, and rebuilds the NCX so every chapter
is listed under its part.

Positions come from paragraph order, not from heading text. The English and
translated bodies are split into sentences, the two sequences are aligned with
a length-based dynamic programme (Gale-Church costs), and the first English
sentence of each chapter is mapped to the translated sentence it aligns with.
Heading residue left by an earlier translation pass is removed only when the
title map lists it explicitly; the module refuses to write when a listed piece
is not found where it is expected.

Run from the repository root::

    python -m src.literary.chapter_headings \\
        --source-en "<English EPUB>" \\
        --epub "translated_files/Ship of Magic (pt-BR).refined.epub" \\
        --titles <title map YAML>
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

import yaml

from .chapter_titles import chapter_label

SPLIT_FILE = re.compile(r"index_split_\d{3}\.html$")
PARAGRAPH = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p>", re.DOTALL)
TOKEN = re.compile(r"<[^>]+>|&#?\w+;|.", re.DOTALL)
TAG = re.compile(r"<[^>]+>")
FOOTER = re.compile(r"\(\d+ of \d+\)\s*\d{1,2}/\d{1,2}/\d{4}(\s*\d{1,2}:\d{2}:\d{2})?")
EN_CHAPTER_LINE = re.compile(r"^CHAPTER\s+([A-Z-]+)\b")
SENTENCE_BREAK = re.compile(r"(?<=[.!?…])[\"”’')\]]*\s+(?=[\"“‘'(\[—–-]?[A-ZÀ-Þ(“—\"'‘])")
END_PUNCT = re.compile(r"[.!?…][\"”’')\]]*\s*$")
NUMBER_WORDS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9,
    "TEN": 10, "ELEVEN": 11, "TWELVE": 12, "THIRTEEN": 13, "FOURTEEN": 14, "FIFTEEN": 15, "SIXTEEN": 16,
    "SEVENTEEN": 17, "EIGHTEEN": 18, "NINETEEN": 19, "TWENTY": 20, "THIRTY": 30,
}
BALANCED_TAGS = ("b", "i", "span", "em", "strong", "a")
RESIDUE_WINDOW = 3  # paragraphs after a chapter's anchor that residue may still occupy


@dataclass(frozen=True)
class Paragraph:
    index: int
    start: int
    end: int
    inner_start: int
    inner: str
    plain: str
    raw_spans: Tuple[Tuple[int, int], ...]  # per plain char: (start, end) offsets inside the source text
    bold: bool


@dataclass
class Sentence:
    owner: int
    offset: int
    text: str


@dataclass(frozen=True)
class Position:
    file: str
    paragraph: int
    offset: int


@dataclass
class ChapterPlan:
    number: int
    en: str
    pt: str
    anchor: Position
    residue: List[Tuple[str, Position, Position]] = field(default_factory=list)
    part: Optional[Dict[str, Any]] = None


# --------------------------------------------------------------------------- parsing


def parse_paragraphs(text: str) -> List[Paragraph]:
    out: List[Paragraph] = []
    for index, match in enumerate(PARAGRAPH.finditer(text)):
        inner = match.group(1)
        base = match.start(1)
        plain: List[str] = []
        spans: List[Tuple[int, int]] = []
        for token in TOKEN.finditer(inner):
            raw = token.group(0)
            if raw.startswith("<"):
                continue
            decoded = html.unescape(raw) if raw.startswith("&") else raw
            for char in decoded:
                plain.append(char)
                spans.append((base + token.start(), base + token.end()))
        out.append(
            Paragraph(
                index=index,
                start=match.start(),
                end=match.end(),
                inner_start=base,
                inner=inner,
                plain="".join(plain),
                raw_spans=tuple(spans),
                bold="<b" in inner,
            )
        )
    return out


def _sentence_spans(plain: str) -> List[Tuple[int, int]]:
    breaks = [m.end() for m in SENTENCE_BREAK.finditer(plain)]
    starts = [0] + breaks
    ends = breaks + [len(plain)]
    spans: List[Tuple[int, int]] = []
    for start, end in zip(starts, ends):
        chunk = plain[start:end]
        if not chunk.strip():
            continue
        lead = len(chunk) - len(chunk.lstrip())
        trail = len(chunk) - len(chunk.rstrip())
        spans.append((start + lead, end - trail))
    return spans


def split_sentences(paragraphs: Sequence[Paragraph]) -> List[Sentence]:
    """Split paragraph text into sentences. A paragraph that does not end a sentence continues into the next one."""
    out: List[Sentence] = []
    open_sentence: Optional[Dict[str, Any]] = None
    previous_ends = True
    for paragraph in paragraphs:
        if not paragraph.plain.strip():
            continue
        for k, (start, end) in enumerate(_sentence_spans(paragraph.plain)):
            piece = paragraph.plain[start:end]
            if k == 0 and open_sentence is not None and not previous_ends:
                open_sentence["parts"].append(piece)
                continue
            if open_sentence is not None:
                out.append(Sentence(open_sentence["owner"], open_sentence["offset"], " ".join(open_sentence["parts"])))
            open_sentence = {"owner": paragraph.index, "offset": start, "parts": [piece]}
        previous_ends = bool(END_PUNCT.search(paragraph.plain.rstrip()))
    if open_sentence is not None:
        out.append(Sentence(open_sentence["owner"], open_sentence["offset"], " ".join(open_sentence["parts"])))
    return out


# --------------------------------------------------------------------------- alignment


def _cost(english: int, translated: int, ratio: float) -> float:
    """Gale-Church length cost: squared deviation from the expected length, scaled by its variance."""
    mean = max(ratio * english, 1.0)
    return (translated - mean) ** 2 / (13.6 * mean)


def align_lengths(english: Sequence[int], translated: Sequence[int], band: int = 200) -> List[Tuple[str, int, int]]:
    """Align two length sequences inside a band around the diagonal.

    Each move is ``11``, ``12``, ``21``, ``10`` or ``01``, listed with its start indices.
    """
    n, m = len(english), len(translated)
    if n == 0 or m == 0:
        raise ValueError("nothing to align")
    ratio = sum(translated) / sum(english)
    best: List[Dict[int, float]] = [{} for _ in range(n + 1)]
    back: List[Dict[int, str]] = [{} for _ in range(n + 1)]
    best[0][0] = 0.0
    for i in range(n + 1):
        center = int(i * m / n)
        for j in range(max(0, center - band), min(m, center + band) + 1):
            here = best[i].get(j)
            if here is None:
                continue
            candidates: List[Tuple[float, int, int, str]] = []
            if i < n and j < m:
                candidates.append((here + _cost(english[i], translated[j], ratio), i + 1, j + 1, "11"))
            if i < n and j + 2 <= m:
                joined = translated[j] + translated[j + 1]
                candidates.append((here + _cost(english[i], joined, ratio) + 2.4, i + 1, j + 2, "12"))
            if i + 2 <= n and j < m:
                joined = english[i] + english[i + 1]
                candidates.append((here + _cost(joined, translated[j], ratio) + 2.4, i + 2, j + 1, "21"))
            if i < n:
                candidates.append((here + 4.6, i + 1, j, "10"))
            if j < m:
                candidates.append((here + 4.6, i, j + 1, "01"))
            for value, ni, nj, move in candidates:
                if value < best[ni].get(nj, float("inf")):
                    best[ni][nj] = value
                    back[ni][nj] = move
    if m not in best[n]:
        raise RuntimeError("sentence alignment left the band")
    path: List[Tuple[str, int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = back[i][j]
        if move == "11":
            i, j = i - 1, j - 1
        elif move == "12":
            i, j = i - 1, j - 2
        elif move == "21":
            i, j = i - 2, j - 1
        elif move == "10":
            i -= 1
        else:
            j -= 1
        path.append((move, i, j))
    path.reverse()
    return path


def english_to_translated(path: Sequence[Tuple[str, int, int]]) -> Dict[int, int]:
    """Map each English sentence to the first translated sentence it aligns with."""
    mapping: Dict[int, int] = {}
    for move, i, j in path:
        if move in ("11", "12"):
            mapping[i] = j
        elif move == "21":
            mapping[i] = j
            mapping[i + 1] = j
    return mapping


# --------------------------------------------------------------------------- title map and English structure


def _norm_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("’", "'").replace("‘", "'")).strip().upper()


def _number(word: str) -> Optional[int]:
    total = 0
    for part in word.split("-"):
        if part not in NUMBER_WORDS:
            return None
        total += NUMBER_WORDS[part]
    return total


def load_spec(path: str | Path) -> Dict[str, Any]:
    """Read the title map. Chapters must be numbered 1..N in order; parts must name the chapter they open."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    chapters = data.get("chapters") or []
    if not chapters:
        raise ValueError(f"{path}: no chapters listed")
    numbers = [int(item["number"]) for item in chapters]
    if numbers != list(range(1, len(chapters) + 1)):
        raise ValueError(f"{path}: chapters must be numbered 1..{len(chapters)} in order, got {numbers}")
    body = data.get("body_start") or {}
    if not body.get("en") or not body.get("pt"):
        raise ValueError(f"{path}: body_start needs en and pt markers")
    parts = [
        {"before": int(item["before"]), "en": str(item["en"]), "pt": str(item["pt"])}
        for item in (data.get("parts") or [])
    ]
    return {
        "book": str(data.get("book") or ""),
        "body_start": {"en": str(body["en"]), "pt": str(body["pt"])},
        "parts": parts,
        "chapters": [
            {
                "number": int(item["number"]),
                "en": str(item["en"]),
                "pt": str(item["pt"]),
                "residue": [str(text) for text in (item.get("residue") or [])],
                "anchor": str(item.get("anchor") or ""),
            }
            for item in chapters
        ],
    }


def english_structure(
    files: Sequence[Tuple[str, str]], spec: Dict[str, Any]
) -> Dict[str, Tuple[List[Paragraph], List[Tuple[int, Dict[str, Any]]]]]:
    """Per file: the English body paragraphs and each chapter heading as (index after the heading, chapter spec).

    A heading is the ``CHAPTER`` line plus the bold continuation lines after it. The heading's English
    title must equal the title map's ``en``; numbers are checked against the map's order.
    """
    running_header = str(spec.get("running_header") or "")
    parts_en = {_norm_title(part["en"]): part for part in spec["parts"]}
    chapters = iter(spec["chapters"])
    started = False
    seen_parts: set = set()
    result: Dict[str, Tuple[List[Paragraph], List[Tuple[int, Dict[str, Any]]]]] = {}
    for name, text in files:
        body: List[Paragraph] = []
        headings: List[Tuple[int, Dict[str, Any]]] = []
        paragraphs = parse_paragraphs(text)
        index = 0
        while index < len(paragraphs):
            paragraph = paragraphs[index]
            plain = paragraph.plain.strip()
            if not started:
                started = _norm_title(plain) == _norm_title(spec["body_start"]["en"])
                index += 1
                continue
            if not plain or (running_header and plain == running_header) or plain.startswith("file:///"):
                index += 1
                continue
            if _norm_title(plain) in parts_en:
                seen_parts.add(_norm_title(plain))
                index += 1
                continue
            match = EN_CHAPTER_LINE.match(plain)
            if match:
                chapter = next(chapters, None)
                if chapter is None:
                    raise ValueError(f"English has more chapter headings than the title map ({plain!r})")
                if _number(match.group(1)) != chapter["number"]:
                    raise ValueError(f"heading {plain!r} is not chapter {chapter['number']} of the title map")
                title_lines = [plain.split(" - ", 1)[1]] if " - " in plain else []
                index += 1
                while index < len(paragraphs):
                    line = paragraphs[index].plain.strip()
                    if paragraphs[index].bold and line and line == line.upper() and len(line) < 60:
                        title_lines.append(line)
                        index += 1
                        continue
                    break
                if _norm_title(" ".join(title_lines)) != _norm_title(chapter["en"]):
                    raise ValueError(f"English title {' '.join(title_lines)!r} does not match {chapter['en']!r}")
                headings.append((index, chapter))
                continue
            body.append(paragraph)
            index += 1
        result[name] = (body, headings)
    if not started:
        raise ValueError("English body start marker not found")
    leftover = next(chapters, None)
    if leftover is not None:
        raise ValueError(f"title map chapter {leftover['number']} was not found in the English body")
    missing = [part["en"] for part in spec["parts"] if _norm_title(part["en"]) not in seen_parts]
    if missing:
        raise ValueError(f"English part headings not found: {missing}")
    return result


def translated_body(paragraphs: Sequence[Paragraph], spec: Dict[str, Any], started: bool) -> Tuple[List[Paragraph], bool]:
    """Translated body paragraphs of one file: non-empty, page footers removed. ``started`` carries across files."""
    body: List[Paragraph] = []
    for paragraph in paragraphs:
        plain = paragraph.plain.strip()
        if not started:
            started = plain.startswith(spec["body_start"]["pt"])
            continue
        if not plain or FOOTER.fullmatch(plain):
            continue
        body.append(paragraph)
    return body, started


# --------------------------------------------------------------------------- residue and planning


def locate_residue(
    paragraphs: Sequence[Paragraph], pieces: Sequence[str], cursor: Tuple[int, int], limit: int, chapter: int
) -> List[Tuple[str, int, int, int]]:
    """Find each residue piece in order: (piece, paragraph, start, end) in plain-text offsets.

    A piece is either a whole paragraph or the start of one, or it continues the previous piece
    in the same paragraph or starts the next paragraph. Pieces are never searched in the middle of body text.
    """
    found: List[Tuple[str, int, int, int]] = []
    for piece in pieces:
        match = None
        for paragraph in paragraphs:
            if paragraph.index < cursor[0] or paragraph.index > limit:
                continue
            if found and paragraph.index < found[-1][1]:
                continue
            plain = paragraph.plain
            lead = len(plain) - len(plain.lstrip())
            if found and paragraph.index == found[-1][1]:
                position = found[-1][3]
                skip = len(plain[position:]) - len(plain[position:].lstrip())
                if plain.startswith(piece, position + skip):
                    match = (piece, paragraph.index, position + skip, position + skip + len(piece))
                    break
                continue
            if plain.strip() == piece or plain.lstrip().startswith(piece):
                match = (piece, paragraph.index, lead, lead + len(piece))
                break
        if match is None:
            raise ValueError(f"chapter {chapter}: residue {piece!r} not found where expected")
        found.append(match)
        if found and len(found) > 1 and found[-1][1] == found[-2][1] and found[-1][2] < found[-2][3]:
            raise ValueError(f"chapter {chapter}: residue pieces overlap")
    return found


def _anchor_by_text(paragraphs: Sequence[Paragraph], text: str, chapter: int, file: str) -> Position:
    """Manual anchor: the one translated paragraph whose text starts with ``text``, checked by hand."""
    hits = [p for p in paragraphs if p.plain.lstrip().startswith(text)]
    if len(hits) != 1:
        raise ValueError(f"chapter {chapter}: anchor {text!r} matched {len(hits)} paragraphs in {file}")
    paragraph = hits[0]
    return Position(file, paragraph.index, len(paragraph.plain) - len(paragraph.plain.lstrip()))


def plan_chapters(
    en_files: Sequence[Tuple[str, str]],
    pt_sources: Dict[str, str],
    spec: Dict[str, Any],
) -> Tuple[List[ChapterPlan], Dict[str, List[Paragraph]]]:
    """Locate each chapter start by paragraph order and the residue to remove before it."""
    structure = english_structure(en_files, spec)
    pt_paragraphs = {name: parse_paragraphs(text) for name, text in pt_sources.items()}
    names = [name for name, _ in en_files]
    started = False
    body_by_file: Dict[str, List[Paragraph]] = {}
    body_start: Optional[Position] = None
    for name in names:
        body, was_started = translated_body(pt_paragraphs[name], spec, started)
        if not started and was_started:
            marker = next(p.index for p in pt_paragraphs[name] if p.plain.strip().startswith(spec["body_start"]["pt"]))
            body_start = Position(name, marker, 0)
        started = was_started
        body_by_file[name] = body
    if body_start is None:
        raise ValueError("translated body start marker not found")
    plans: List[ChapterPlan] = []
    cursor = body_start
    for name in names:
        en_body, headings = structure[name]
        if not headings:
            continue
        en_sents = split_sentences(en_body)
        pt_sents = split_sentences(body_by_file[name])
        mapping = english_to_translated(
            align_lengths([len(s.text) for s in en_sents], [len(s.text) for s in pt_sents])
        )
        for heading_end, chapter in headings:
            first = next((k for k, s in enumerate(en_sents) if s.owner >= heading_end), None)
            if first is None:
                raise ValueError(f"chapter {chapter['number']}: no English body text after the heading")
            k = first
            while k < len(en_sents) and k not in mapping:
                k += 1
            if k >= len(en_sents):
                raise ValueError(f"chapter {chapter['number']}: no aligned translated text")
            target = pt_sents[mapping[k]]
            anchor = Position(name, target.owner, target.offset)
            if chapter["anchor"]:
                anchor = _anchor_by_text(pt_paragraphs[name], chapter["anchor"], chapter["number"], name)
            start_at = (cursor.paragraph, cursor.offset) if cursor.file == name else (0, 0)
            found = locate_residue(
                pt_paragraphs[name], chapter["residue"], start_at, anchor.paragraph + RESIDUE_WINDOW, chapter["number"]
            )
            residue = [
                (piece, Position(name, para, start), Position(name, para, end))
                for piece, para, start, end in found
            ]
            plans.append(ChapterPlan(chapter["number"], chapter["en"], chapter["pt"], anchor, residue))
            cursor = anchor
    for number, part in enumerate(spec["parts"], start=1):
        target = next((plan for plan in plans if plan.number == part["before"]), None)
        if target is None:
            raise ValueError(f"part {part['en']!r} opens chapter {part['before']}, which is not in the title map")
        target.part = {**part, "number": number}
    return plans, pt_paragraphs


# --------------------------------------------------------------------------- rendering


@dataclass
class _Edit:
    removals: List[Tuple[int, int]] = field(default_factory=list)  # plain-text spans to delete
    whole: bool = False  # the whole paragraph is residue
    inserts: List[Tuple[int, str]] = field(default_factory=list)  # (plain offset, heading markup)


def _visible(markup: str) -> str:
    return html.unescape(TAG.sub("", markup)).strip()


def _cut(text: str, base: int, ranges: Sequence[Tuple[int, int]]) -> str:
    """Delete the absolute ``ranges`` that fall inside ``text``, which starts at absolute offset ``base``."""
    out: List[str] = []
    cursor = base
    for start, end in sorted(ranges):
        start, end = max(start, base), min(end, base + len(text))
        if end <= start:
            continue
        out.append(text[cursor - base : start - base])
        cursor = end
    out.append(text[cursor - base :])
    return "".join(out)


def _balanced(markup: str) -> bool:
    return all(
        len(re.findall(rf"<{tag}[\s>]", markup)) == len(re.findall(rf"</{tag}>", markup)) for tag in BALANCED_TAGS
    )


def _render(source: str, paragraph: Paragraph, edit: _Edit) -> str:
    heads = "".join(markup for _, markup in edit.inserts)
    if edit.whole:
        return heads
    removals = [(paragraph.raw_spans[s][0], paragraph.raw_spans[e - 1][1]) for s, e in edit.removals]
    opening = source[paragraph.start : paragraph.inner_start]
    if not edit.inserts:
        inner = _cut(paragraph.inner, paragraph.inner_start, removals)
        return opening + inner + "</p>" if _visible(inner) else ""
    if len(edit.inserts) != 1:
        raise ValueError(f"more than one heading in paragraph {paragraph.index}")
    offset = edit.inserts[0][0]
    split = paragraph.raw_spans[offset][0] if offset < len(paragraph.plain) else paragraph.inner_start + len(paragraph.inner)
    head_text = source[paragraph.inner_start : split]
    tail_text = source[split : paragraph.inner_start + len(paragraph.inner)]
    prefix = _cut(head_text, paragraph.inner_start, removals)
    suffix = _cut(tail_text, split, removals)
    if not _balanced(prefix) or not _balanced(suffix):
        raise ValueError(f"heading split inside inline markup (paragraph {paragraph.index})")
    out = opening + prefix + "</p>" if _visible(prefix) else ""
    out += heads
    if _visible(suffix):
        out += opening + suffix + "</p>"
    return out


def render_file(source: str, paragraphs: Sequence[Paragraph], edits: Dict[int, _Edit]) -> str:
    out: List[str] = []
    cursor = 0
    for paragraph in paragraphs:
        if paragraph.index not in edits:
            continue
        out.append(source[cursor : paragraph.start])
        out.append(_render(source, paragraph, edits[paragraph.index]))
        cursor = paragraph.end
    out.append(source[cursor:])
    return "".join(out)


def chapter_heading_html(number: int, title_pt: str) -> str:
    return (
        f'<h2 class="chapter-number" id="chapter-{number}">CAPÍTULO {number}</h2>\n'
        f'<h2 class="chapter-title">{escape(title_pt.upper())}</h2>\n'
    )


def part_heading_html(number: int, title_pt: str) -> str:
    return f'<h2 class="part-title" id="part-{number}">{escape(title_pt.upper())}</h2>\n'


def build_edits(
    plans: Sequence[ChapterPlan], pt_paragraphs: Dict[str, List[Paragraph]]
) -> Dict[str, Dict[int, _Edit]]:
    """Group residue removals and heading insertions by file and paragraph."""
    edits: Dict[str, Dict[int, _Edit]] = {}
    for plan in plans:
        for piece, start, end in plan.residue:
            paragraph = pt_paragraphs[start.file][start.paragraph]
            edit = edits.setdefault(start.file, {}).setdefault(start.paragraph, _Edit())
            if paragraph.plain.strip() == piece:
                edit.whole = True
            edit.removals.append((start.offset, end.offset))
        insert_at = plan.residue[0][1] if plan.residue else plan.anchor
        markup = ""
        if plan.part is not None:
            markup += part_heading_html(plan.part["number"], plan.part["pt"])
        markup += chapter_heading_html(plan.number, plan.pt)
        edit = edits.setdefault(insert_at.file, {}).setdefault(insert_at.paragraph, _Edit())
        edit.inserts.append((insert_at.offset, markup))
    return edits


# --------------------------------------------------------------------------- NCX and packaging


def _nav_point(point_id: str, order: int, label: str, src: str, children: str = "") -> str:
    return (
        f'<navPoint id="{point_id}" playOrder="{order}"><navLabel><text>{escape(label)}</text></navLabel>'
        f'<content src="{escape(src)}"/>{children}</navPoint>'
    )


def build_ncx(ncx_text: str, plans: Sequence[ChapterPlan], spec: Dict[str, Any]) -> str:
    """Rewrite the navMap: each part with its chapters nested under it; chapters link to their anchors."""
    head = ncx_text[: ncx_text.index("<navMap")]
    tail = ncx_text[ncx_text.index("</navMap>") + len("</navMap>") :]
    order = 0

    def next_order() -> int:
        nonlocal order
        order += 1
        return order

    entries: List[str] = []
    current_children: Optional[List[str]] = None
    current_part: Optional[Tuple[ChapterPlan, int]] = None
    for plan in plans:
        if plan.part is not None:
            if current_part is not None:
                entries.append(_part_entry(current_part, current_children or [], next_order))
            current_part = (plan, plan.part["number"])
            current_children = []
        chapter_entry = _nav_point(
            f"nav-chapter-{plan.number}",
            next_order(),
            chapter_label(plan.number, plan.pt),
            f"{plan.anchor.file}#chapter-{plan.number}",
        )
        if current_children is None:
            entries.append(chapter_entry)
        else:
            current_children.append(chapter_entry)
    if current_part is not None:
        entries.append(_part_entry(current_part, current_children or [], next_order))
    return head + "<navMap>" + "".join(entries) + "</navMap>" + tail


def _part_entry(part: Tuple[ChapterPlan, int], children: List[str], next_order: Any) -> str:
    plan, number = part
    label = f"Parte {number} {plan.part['pt'].upper()}"
    return _nav_point(f"nav-part-{number}", next_order(), label, f"{plan.anchor.file}#part-{number}", "".join(children))


def _read_members(path: str | Path) -> Tuple[List[str], Dict[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        names = [info.filename for info in archive.infolist()]
        return names, {name: archive.read(name) for name in names}


def write_epub(output: str | Path, names: Sequence[str], members: Dict[str, bytes], changed: Dict[str, bytes]) -> None:
    with zipfile.ZipFile(output, "w") as archive:
        for name in names:
            compress = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            archive.writestr(name, changed.get(name, members[name]), compress_type=compress)


def restore_epub(source_en: str | Path, epub: str | Path, spec_path: str | Path, output: str | Path) -> Dict[str, Any]:
    """Write ``output``: the translated EPUB with chapter headings, part headings and a rebuilt NCX."""
    spec = load_spec(spec_path)
    names, members = _read_members(epub)
    en_names, en_members = _read_members(source_en)
    split_names = sorted(name for name in names if SPLIT_FILE.search(name))
    if sorted(name for name in en_names if SPLIT_FILE.search(name))[: len(split_names)] != split_names:
        raise ValueError("English and translated split files do not match by name")
    sources = {name: members[name].decode("utf-8") for name in split_names}
    en_files = [(name, en_members[name].decode("utf-8")) for name in split_names]
    plans, pt_paragraphs = plan_chapters(en_files, sources, spec)
    edits = build_edits(plans, pt_paragraphs)
    changed: Dict[str, bytes] = {}
    for name, per_paragraph in edits.items():
        if any(f'id="chapter-{n}"' in sources[name] or f'id="part-{n}"' in sources[name] for n in range(1, 40)):
            raise ValueError(f"{name}: heading ids already present")
        changed[name] = render_file(sources[name], pt_paragraphs[name], per_paragraph).encode("utf-8")
    ncx_name = next(name for name in names if name.lower().endswith(".ncx"))
    changed[ncx_name] = build_ncx(members[ncx_name].decode("utf-8"), plans, spec).encode("utf-8")
    write_epub(output, names, members, changed)
    return {
        "chapters": [
            {
                "number": plan.number,
                "file": plan.anchor.file,
                "residue": [piece for piece, _, _ in plan.residue],
                "part": plan.part["pt"] if plan.part else None,
            }
            for plan in plans
        ],
        "changed_files": sorted(changed),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--epub", required=True, type=Path, help="translated EPUB to update in place")
    parser.add_argument("--source-en", required=True, type=Path, help="English source EPUB")
    parser.add_argument("--titles", required=True, type=Path, help="chapter title map (YAML)")
    parser.add_argument("--epubcheck-dir", type=Path, help="folder with epubcheck-*.jar (defaults to the queue's)")
    args = parser.parse_args(argv)

    from . import queue_runner
    from .validation import validate_epub_pair

    if args.epubcheck_dir:
        queue_runner.EPUBCHECK_DIR = args.epubcheck_dir
    stage = args.epub.with_name(f".{args.epub.stem}.chapters.tmp.epub")
    try:
        report = restore_epub(args.source_en, args.epub, args.titles, stage)
        validation = validate_epub_pair(str(args.source_en), str(stage), expected_language="pt-BR")
        epubcheck = queue_runner._epubcheck(stage)
        passed = bool(validation.get("passed")) and epubcheck.get("errors") == 0
        report["gate"] = {
            "passed": passed,
            "pair_passed": bool(validation.get("passed")),
            "pair_blocking": validation.get("blocking"),
            "pair_issue_codes": sorted({str(getattr(issue, "code", issue)) for issue in validation.get("issues", [])}),
            "epubcheck_errors": epubcheck.get("errors"),
            "epubcheck_warnings": epubcheck.get("warnings"),
        }
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
