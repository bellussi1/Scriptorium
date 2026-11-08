"""Source-aware selective refinement for an already translated EPUB.

The upstream refinement pass is blind: it sees only the Portuguese draft. This
module pairs the source and target spine documents paragraph by paragraph, flags
only segments with deterministic issues (numbers, glossary, PT-BR grammar,
placeholder drift), asks the model to revise those segments with the source in
front of it, and applies only revisions the guard accepts.

Paragraphs containing inline markup (italics, spans, dropcaps) are skipped by
default: replacing their inner HTML would destroy the markup. The report counts
them so the loss is visible instead of silent.
"""
from __future__ import annotations

import html
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .continuity import ContinuityTracker
from .epub import iter_spine_documents
from .models import CompiledResources
from .refine_runner import (
    FlaggedSegment,
    flags_for_segment,
    generate_ollama,
    refine_segments,
)


_PARAGRAPH_RE = re.compile(r"<p\b[^>]*>(.*?)</p\s*>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Paragraph:
    index: int
    inner: str
    text: str
    start: int
    end: int
    has_inline_markup: bool


def extract_paragraphs(raw: str) -> List[Paragraph]:
    """Extract plain-text paragraphs and their inner-content spans."""
    paragraphs: List[Paragraph] = []
    for match in _PARAGRAPH_RE.finditer(raw or ""):
        inner = match.group(1)
        text = html.unescape(_TAG_RE.sub("", inner)).strip()
        if not text:
            continue
        paragraphs.append(
            Paragraph(
                index=len(paragraphs),
                inner=inner,
                text=text,
                start=match.start(1),
                end=match.end(1),
                has_inline_markup=bool(_TAG_RE.search(inner)),
            )
        )
    return paragraphs


def apply_paragraph_replacements(
    raw: str,
    paragraphs: Sequence[Paragraph],
    replacements: Dict[int, str],
) -> str:
    """Replace the inner HTML of plain paragraphs without touching the markup."""
    if not replacements:
        return raw
    parts: List[str] = []
    cursor = 0
    for paragraph in paragraphs:
        if paragraph.index not in replacements:
            continue
        parts.append(raw[cursor : paragraph.start])
        parts.append(html.escape(replacements[paragraph.index], quote=False))
        cursor = paragraph.end
    parts.append(raw[cursor:])
    return "".join(parts)


def _book_documents(path: str) -> List[Dict[str, object]]:
    return list(iter_spine_documents(path))


def _pair_documents(
    source_docs: Sequence[Dict[str, object]],
    target_docs: Sequence[Dict[str, object]],
) -> Tuple[List[Tuple[Dict[str, object], Dict[str, object]]], int, int]:
    """Pair documents by href first, then fall back to spine order."""
    if len(source_docs) == len(target_docs):
        return list(zip(source_docs, target_docs)), 0, 0
    target_by_href = {str(doc.get("href")): doc for doc in target_docs}
    pairs: List[Tuple[Dict[str, object], Dict[str, object]]] = []
    used: set[int] = set()
    for source_doc in source_docs:
        target_doc = target_by_href.get(str(source_doc.get("href")))
        if target_doc is None or id(target_doc) in used:
            continue
        pairs.append((source_doc, target_doc))
        used.add(id(target_doc))
    # Fill the remaining slots in order, but never pair the same target twice.
    remaining_source = [doc for doc in source_docs if all(doc is not pair[0] for pair in pairs)]
    remaining_target = [doc for doc in target_docs if id(doc) not in used]
    filler = list(zip(remaining_source, remaining_target))
    pairs.extend(filler)
    return pairs, len(source_docs) - len(pairs), len(target_docs) - len(pairs)


def refine_epub(
    source_path: str,
    target_path: str,
    output_path: str,
    *,
    model: str,
    compiled: Optional[CompiledResources] = None,
    style: str = "",
    continuity: Optional[ContinuityTracker] = None,
    endpoint: str = "http://localhost:11434",
    temperature: float = 0.0,
    max_tokens: int = 800,
    num_ctx: int = 8192,
    limit: int = 0,
    dry_run: bool = False,
    generate: Optional[Callable[[List[Dict[str, str]]], str]] = None,
) -> Dict[str, object]:
    """Refine flagged paragraphs in ``target_path`` and write ``output_path``."""
    source_docs = _book_documents(source_path)
    target_docs = _book_documents(target_path)
    document_pairs, extra_source, extra_target = _pair_documents(source_docs, target_docs)

    if generate is None:
        def generate(messages: List[Dict[str, str]]) -> str:
            return generate_ollama(
                messages,
                model=model,
                endpoint=endpoint,
                temperature=temperature,
                max_tokens=max_tokens,
                num_ctx=num_ctx,
            )

    tracker = continuity
    report: Dict[str, object] = {
        "source": os.path.abspath(source_path),
        "target": os.path.abspath(target_path),
        "output": os.path.abspath(output_path),
        "model": model,
        "documents": len(source_docs),
        "documents_refined": 0,
        "documents_skipped": [],
        "paragraphs": 0,
        "paragraphs_compared": 0,
        "paragraphs_inline_markup_skipped": 0,
        "flagged": 0,
        "attempted": 0,
        "accepted": 0,
        "rejected": 0,
        "accepted_segments": [],
    }

    changed: Dict[str, bytes] = {}
    remaining = limit if limit and limit > 0 else 0

    if extra_source or extra_target:
        report["documents_skipped"].append(
            {
                "reason": "spine_count_mismatch",
                "source_documents": len(source_docs),
                "target_documents": len(target_docs),
                "extra_source": extra_source,
                "extra_target": extra_target,
            }
        )

    for source_doc, target_doc in document_pairs:
        href = str(target_doc.get("href") or "")
        source_paragraphs = extract_paragraphs(str(source_doc.get("raw") or ""))
        target_paragraphs = extract_paragraphs(str(target_doc.get("raw") or ""))
        report["paragraphs"] = int(report["paragraphs"]) + len(target_paragraphs)

        if len(source_paragraphs) != len(target_paragraphs):
            report["documents_skipped"].append(
                {
                    "href": href,
                    "reason": "paragraph_count_mismatch",
                    "source_paragraphs": len(source_paragraphs),
                    "target_paragraphs": len(target_paragraphs),
                }
            )
            continue

        flagged: List[FlaggedSegment] = []
        for source_paragraph, target_paragraph in zip(source_paragraphs, target_paragraphs):
            report["paragraphs_compared"] = int(report["paragraphs_compared"]) + 1
            if source_paragraph.has_inline_markup or target_paragraph.has_inline_markup:
                report["paragraphs_inline_markup_skipped"] = (
                    int(report["paragraphs_inline_markup_skipped"]) + 1
                )
                continue
            issues = flags_for_segment(
                source_paragraph.text,
                target_paragraph.text,
                compiled=compiled,
            )
            if issues:
                flagged.append(
                    FlaggedSegment(
                        index=target_paragraph.index,
                        source=source_paragraph.text,
                        draft=target_paragraph.text,
                        issues=issues,
                    )
                )

        report["flagged"] = int(report["flagged"]) + len(flagged)
        if not flagged:
            if tracker is not None:
                tracker.update(str(source_doc.get("text") or ""))
            continue

        selected = flagged
        if limit and limit > 0:
            if remaining <= 0:
                break
            selected = flagged[:remaining]
            remaining -= len(selected)

        if dry_run:
            if tracker is not None:
                tracker.update(str(source_doc.get("text") or ""))
            continue

        replacements, segment_report = refine_segments(
            selected,
            generate,
            compiled=compiled,
            style=style,
            continuity=tracker.block() if tracker is not None else "",
        )
        report["attempted"] = int(report["attempted"]) + int(segment_report.get("attempted", 0))
        report["accepted"] = int(report["accepted"]) + int(segment_report.get("accepted", 0))
        report["rejected"] = int(report["rejected"]) + int(segment_report.get("rejected", 0))
        for entry in segment_report.get("segments", []):
            if entry.get("accepted"):
                report["accepted_segments"].append(
                    {"href": href, "index": entry.get("index")}
                )

        if replacements:
            changed[str(target_doc.get("path") or href)] = apply_paragraph_replacements(
                str(target_doc.get("raw") or ""), target_paragraphs, replacements
            ).encode("utf-8")
            report["documents_refined"] = int(report["documents_refined"]) + 1

        if tracker is not None:
            tracker.update(str(source_doc.get("text") or ""))

    _write_epub(target_path, output_path, changed)
    return report


def _write_epub(source_path: str, output_path: str, changed: Dict[str, bytes]) -> None:
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    temp_path = output_path + ".tmp"
    with zipfile.ZipFile(source_path, "r") as source, zipfile.ZipFile(
        temp_path, "w", zipfile.ZIP_DEFLATED
    ) as target:
        for item in source.infolist():
            data = changed.get(item.filename)
            if data is None:
                data = source.read(item.filename)
            target.writestr(item, data)
    os.replace(temp_path, output_path)
