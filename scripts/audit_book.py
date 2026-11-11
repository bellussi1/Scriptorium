"""Audit one finished literary translation before auto-approving it.

The queue runner already validates the EPUB pair and runs EPUBCheck. This
script adds the editorial gates that a human would otherwise check:

- glossary target coverage and forbidden renderings;
- pt-PT markers, English leakage, repetition and length ratio;
- eight source/target samples reviewed by a cheap cloud model (Haiku): factual
  meaning errors gate the book, style notes (calques, lost irony, weakened
  imagery) are advisory.

It is deliberately conservative: a missing API key, an API error or a budget
cap breach fails the audit and leaves the book in ``needs_review``.

Usage:
    python scripts/audit_book.py --book-id 10 --job-id 19 \
      --report data/queue-runs/howling-dark.report.json --max-cloud-usd 0.05
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.literary.metrics import english_leakage, length_ratio, repetition_ratio  # noqa: E402
from src.literary.per_file_audit import PT_PT_PATTERNS, scan_book  # noqa: E402
from src.literary.queue import QueueStore  # noqa: E402
from src.literary.resources import compile_for_book, load_tree  # noqa: E402
from src.literary.run_plan import build_run_plan  # noqa: E402
from src.literary.validation import glossary_target_present  # noqa: E402

LEDGER = ROOT / "data" / "cost_ledger.jsonl"
AUDIT_ROOT = ROOT / "data" / "audits"

TRANSLATED_CATEGORIES = {
    "character",
    "title",
    "location",
    "organization",
    "concept",
    "other",
    "item",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "book"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _epub_text(path: Path) -> Tuple[str, List[Tuple[str, List[str]]]]:
    """Return full text and (xhtml name, paragraphs) pairs."""
    files: List[Tuple[str, List[str]]] = []
    full: List[str] = []
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm"))
            and not name.startswith("META-INF/")
        ]
        for name in sorted(names):
            raw = archive.read(name).decode("utf-8", errors="replace")
            raw = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.S | re.I)
            raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
            raw = re.sub(r"</(p|div|h[1-6]|li|blockquote|section)>", "\n", raw, flags=re.I)
            raw = re.sub(r"<[^>]+>", " ", raw)
            text = html.unescape(raw)
            paragraphs = []
            for part in text.split("\n"):
                part = re.sub(r"\s+", " ", part).strip()
                if len(part.split()) >= 5:
                    paragraphs.append(part)
            if paragraphs:
                files.append((name, paragraphs))
                full.extend(paragraphs)
    return "\n\n".join(full), files


def _align_paragraphs(
    source_counts: List[int], target_counts: List[int]
) -> Dict[int, Tuple[int, int]]:
    """Align paragraph sequences by word-count signature.

    The translated EPUB splits dialogue and merges chunk seams, so the same
    paragraph index no longer describes the same scene. Align the two word-count
    sequences with a small dynamic program that allows 1:1, 1:2 (a split) and
    2:1 (a merge) blocks; the mapping is stable even when a chapter gains
    hundreds of short dialogue paragraphs.
    """
    n, m = len(source_counts), len(target_counts)
    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    back: List[List[Optional[Tuple[int, int, str, int, int]]]] = [
        [None] * (m + 1) for _ in range(n + 1)
    ]
    dp[0][0] = 0.0
    skip_cost = 1.5

    def relax(i: int, j: int, cost: float, step: Tuple[int, int, str, int, int]) -> None:
        if cost < dp[i][j]:
            dp[i][j] = cost
            back[i][j] = step

    for i in range(n + 1):
        for j in range(m + 1):
            base = dp[i][j]
            if base == inf:
                continue
            if i < n:
                relax(i + 1, j, base + skip_cost, (i, j, "skip_s", i, j))
            if j < m:
                relax(i, j + 1, base + skip_cost, (i, j, "skip_t", i, j))
            if i < n and j < m:
                cost = abs(math.log((target_counts[j] + 1) / (source_counts[i] + 1)))
                relax(i + 1, j + 1, base + cost, (i, j, "1:1", i, j))
            if i < n and j + 1 < m:
                cost = (
                    abs(
                        math.log(
                            (target_counts[j] + target_counts[j + 1] + 1)
                            / (source_counts[i] + 1)
                        )
                    )
                    + 0.05
                )
                relax(i + 1, j + 2, base + cost, (i, j, "1:2", i, j))
            if i + 1 < n and j < m:
                cost = (
                    abs(
                        math.log(
                            (target_counts[j] + 1)
                            / (source_counts[i] + source_counts[i + 1] + 1)
                        )
                    )
                    + 0.05
                )
                relax(i + 2, j + 1, base + cost, (i, j, "2:1", i, j))

    mapping: Dict[int, Tuple[int, int]] = {}
    i, j = n, m
    while i > 0 or j > 0:
        step = back[i][j]
        if step is None:
            break
        pi, pj, kind, i0, j0 = step
        if kind == "1:1":
            mapping[i0] = (j0, j0 + 1)
        elif kind == "1:2":
            mapping[i0] = (j0, j0 + 2)
        elif kind == "2:1":
            mapping[i0] = (j0, j0 + 1)
            mapping[i0 + 1] = (j0, j0 + 1)
        i, j = pi, pj
    return mapping


def _sample_pairs(
    source_files: List[Tuple[str, List[str]]],
    target_files: List[Tuple[str, List[str]]],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    target_by_name = {name: paragraphs for name, paragraphs in target_files}
    candidates = [
        (name, paragraphs)
        for name, paragraphs in source_files
        if name in target_by_name and len(paragraphs) >= 4
    ]
    if not candidates:
        return []
    if len(candidates) > limit:
        step = max(1, len(candidates) // limit)
        candidates = candidates[::step][:limit]
    samples = []
    for name, source_paragraphs in candidates:
        target_paragraphs = target_by_name[name]
        mapping = _align_paragraphs(
            [len(paragraph.split()) for paragraph in source_paragraphs],
            [len(paragraph.split()) for paragraph in target_paragraphs],
        )
        best: Optional[Tuple[int, str, str]] = None
        for index, source in enumerate(source_paragraphs):
            words = len(source.split())
            if not 40 <= words <= 220:
                continue
            span = mapping.get(index)
            if not span:
                continue
            start, end = span
            target = " ".join(target_paragraphs[start:end]).strip()
            target_words = len(target.split())
            if not target_words:
                continue
            ratio = target_words / words
            if 0.55 <= ratio <= 1.8:
                best = (index, source, target)
                break
        if best:
            index, source, target = best
            samples.append(
                {
                    "id": f"{name}:{index}",
                    "file": name,
                    "paragraph": index,
                    "source": source,
                    "target": target,
                }
            )
    return samples


def _load_glossary_snapshot(path: Path) -> List[Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    terms = []
    for row in data.get("terms") or []:
        if not isinstance(row, dict) or not row.get("source"):
            continue
        forms = [
            part.strip()
            for part in str(row.get("source") or "").split("|")
            if part.strip()
        ]
        if not forms:
            continue
        target = str(row.get("target") or "")
        aliases = forms[1:]
        terms.append(
            SimpleNamespace(
                source=forms[0],
                target=target,
                category=str(row.get("category") or "other"),
                aliases=aliases,
                alias_targets={alias: target for alias in aliases},
                forbidden=list(row.get("forbidden") or []),
                policy=str(row.get("policy") or ""),
                confidence=str(row.get("confidence") or ""),
                source_reference=str(row.get("source_reference") or ""),
            )
        )
    return terms


def _term_form_map(terms: List[Any]) -> Dict[str, Tuple[str, Tuple[str, ...]]]:
    mapping: Dict[str, Tuple[str, Tuple[str, ...]]] = {}
    for term in terms:
        forbidden = tuple(
            sorted(str(item) for item in (getattr(term, "forbidden", []) or []))
        )
        mapping[term.source] = (term.target, forbidden)
        alias_targets = getattr(term, "alias_targets", {}) or {}
        for alias in getattr(term, "aliases", []) or []:
            mapping[alias] = (alias_targets.get(alias, term.target), forbidden)
    return mapping


def _resolve_terms(
    book: Any,
    glossary_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Resolve the glossary snapshot (or the current compiled terms).

    The snapshot is what the run actually used; the compiled tree is only a
    fallback when the run report has no snapshot. Both are returned so the
    per-file scan can reuse the same terms without compiling twice.
    """
    current_terms: List[Any] = []
    current_map: Dict[str, Tuple[str, Tuple[str, ...]]] = {}
    snapshot_terms: List[Any] = []
    snapshot = ""
    error = ""
    try:
        plan = build_run_plan(book)
        scopes = plan.get("scopes") or {}
        tree = load_tree(str(ROOT / "literary-resources"))
        compiled = compile_for_book(
            tree,
            scopes.get("author", ""),
            scopes.get("universe", ""),
            scopes.get("subseries", ""),
            scopes.get("book", ""),
            book_order=book.series_index,
        )
        current_terms = compiled.glossary.terms
        current_map = _term_form_map(current_terms)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    if glossary_path and Path(glossary_path).exists():
        snapshot_terms = _load_glossary_snapshot(Path(glossary_path))
        snapshot = str(glossary_path)
        terms = snapshot_terms
    elif error and not current_terms:
        return {
            "terms": [],
            "current_terms": [],
            "current_map": {},
            "snapshot": "",
            "error": error,
        }
    else:
        terms = current_terms

    return {
        "terms": terms,
        "current_terms": current_terms,
        "current_map": current_map,
        "snapshot": snapshot,
        "error": "",
    }


def _term_audit(
    book: Any,
    source_text: str,
    target_text: str,
    *,
    glossary_path: Optional[Path] = None,
    resolved: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = resolved if resolved is not None else _resolve_terms(book, glossary_path)
    if data.get("error"):
        return {
            "ok": False,
            "error": data["error"],
            "coverage": None,
            "forbidden_hits": [],
            "missing": [],
        }

    terms = data["terms"]
    current_terms = data["current_terms"]
    current_map = data["current_map"]
    snapshot_terms = terms if data["snapshot"] else []
    snapshot = data["snapshot"]

    source_cf = source_text.casefold()
    eligible = 0
    hits = 0
    missing: List[Dict[str, str]] = []
    forbidden_hits: List[Dict[str, Any]] = []
    drift: List[Dict[str, Any]] = []
    for term in terms:
        if snapshot_terms and current_map:
            current = current_map.get(term.source)
            if current is None:
                drift.append(
                    {
                        "source": term.source,
                        "snapshot_target": term.target,
                        "current_target": "",
                        "reason": "removed from the current glossary",
                    }
                )
                continue
            current_target, current_forbidden = current
            if current_target != term.target or set(current_forbidden) != set(term.forbidden):
                drift.append(
                    {
                        "source": term.source,
                        "snapshot_target": term.target,
                        "current_target": current_target,
                        "reason": "glossary changed after the run",
                    }
                )
                continue
        forms = [term.source] + list(getattr(term, "aliases", []) or [])
        if not any(form.casefold() in source_cf for form in forms if form):
            continue
        targets = [term.target]
        alias_targets = getattr(term, "alias_targets", {}) or {}
        targets.extend(alias_targets.values())
        targets = [target for target in targets if target]
        if targets:
            eligible += 1
            if any(glossary_target_present(target, target_text) for target in targets):
                hits += 1
            else:
                missing.append(
                    {
                        "source": term.source,
                        "target": term.target,
                        "category": getattr(term, "category", ""),
                    }
                )
        for forbidden in getattr(term, "forbidden", []) or []:
            count = len(
                re.findall(
                    rf"\b{re.escape(str(forbidden))}\b",
                    target_text,
                    flags=re.I,
                )
            )
            if count:
                forbidden_hits.append({"source": term.source, "forbidden": forbidden, "count": count})
    coverage = (hits / eligible) if eligible else 1.0
    return {
        "ok": True,
        "terms": len(terms),
        "snapshot": snapshot,
        "snapshot_terms": len(snapshot_terms) if snapshot_terms else None,
        "current_terms": len(current_terms),
        "drift": drift[:50],
        "eligible": eligible,
        "hits": hits,
        "coverage": round(coverage, 4),
        "missing": missing[:25],
        "forbidden_hits": forbidden_hits,
    }


def _text_metrics(source_text: str, target_text: str) -> Dict[str, Any]:
    target_words = max(1, len(re.findall(r"\b\w+\b", target_text)))
    pt_hits = []
    for pattern in PT_PT_PATTERNS:
        matches = re.findall(pattern, target_text, flags=re.I)
        if matches:
            pt_hits.append({"pattern": pattern, "count": len(matches)})
    pt_total = sum(item["count"] for item in pt_hits)
    try:
        leakage = english_leakage(target_text)
    except Exception:
        leakage = None
    try:
        repetition = repetition_ratio(target_text)
    except Exception:
        repetition = None
    try:
        ratio = length_ratio(source_text, target_text)
    except Exception:
        ratio = None
    return {
        "words": target_words,
        "pt_pt_hits": pt_hits,
        "pt_pt_total": pt_total,
        "pt_pt_per_100k": round(pt_total / target_words * 100_000, 2),
        "english_leakage": leakage,
        "repetition_ratio": repetition,
        "length_ratio": ratio,
    }


def _cloud_prompt(samples: List[Dict[str, Any]]) -> str:
    lines = [
        "You are auditing a literary translation from English into Brazilian Portuguese.",
        "For each pair, judge fidelity, naturalness, terminology, register and prose on a 1-5 scale.",
        "Check the verb tense against the source's narrative frame. Count unjustified tense shifts as tense_errors; the retrospective past frame must stay past.",
        "Check grammatical gender agreement for characters, nouns and glossary terms. Count errors as gender_errors; a female character or a feminine noun must not default to masculine.",
        "Classify every finding in exactly one bucket. meaning_errors counts only factual or denotative errors: a wrong referent, an inverted relation, a dropped proposition that changes what happens, an added fact, or a wrong number, name or term. Do not count calques, lost irony, weakened imagery, awkward collocation, register shifts, or an untranslated loanword that is still understandable; those are style_notes.",
        "A faithful passage can still have style_notes. style_notes are advisory and do not fail the book; do not inflate meaning_errors with style issues. Use the same finding in both fields only when a style choice also changes the facts.",
        "Flag pt-PT forms (tu, contacto, de facto, demónio, a dançar) and English leakage in notes; do not count them as meaning_errors.",
        "If the target does not correspond to the source paragraph, set alignment_suspect to true and do not score it.",
        "Return ONLY a JSON object with this shape:",
        '{"items":[{"id":"...","alignment_suspect":false,"fidelity":1,"naturalness":1,"terminology":1,"register":1,"prose":1,"meaning_errors":0,"style_notes":0,"tense_errors":0,"gender_errors":0,"notes":"short Portuguese note"}],"summary":"short Portuguese summary"}',
        "Do not use markdown fences. Do not add commentary outside the JSON.",
        "",
    ]
    for sample in samples:
        lines.extend(
            [
                f"ID: {sample['id']}",
                "SOURCE:",
                sample["source"],
                "",
                "TARGET:",
                sample["target"],
                "",
            ]
        )
    return "\n".join(lines)


def _cloud_verdict(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply the cloud gate to the judge's items.

    ``meaning_errors`` is factual and gates the book. ``style_notes`` covers
    calques, lost irony, weakened imagery and similar editorial notes; it is
    reported and may raise an advisory warning, but it never fails the book.
    """
    scored = [
        item
        for item in items
        if isinstance(item, dict) and not item.get("alignment_suspect")
    ]

    def average(key_name: str) -> float:
        values = [float(item.get(key_name) or 0) for item in scored]
        return round(sum(values) / len(values), 3) if values else 0.0

    averages = {
        "fidelity": average("fidelity"),
        "naturalness": average("naturalness"),
        "terminology": average("terminology"),
        "register": average("register"),
        "prose": average("prose"),
    }
    meaning_errors = sum(int(item.get("meaning_errors") or 0) for item in scored)
    meaning_candidates = sum(
        int(item.get("meaning_candidates", item.get("meaning_errors") or 0))
        for item in scored
    )
    style_notes = sum(int(item.get("style_notes") or 0) for item in scored)
    tense_errors = sum(int(item.get("tense_errors") or 0) for item in scored)
    gender_errors = sum(int(item.get("gender_errors") or 0) for item in scored)

    warnings: List[str] = []
    if style_notes > max(3, len(scored)):
        warnings.append(
            f"high style-note count: {style_notes} across {len(scored)} scored "
            "samples (advisory)"
        )
    if meaning_errors == 1:
        warnings.append("one factual meaning error tolerated by the gate")
    if meaning_candidates > meaning_errors:
        warnings.append(
            f"{meaning_candidates - meaning_errors} candidate meaning error(s) "
            "not confirmed by the second pass"
        )

    passed = (
        len(scored) >= 3
        and averages["fidelity"] >= 3.5
        and averages["naturalness"] >= 3.5
        and averages["prose"] >= 3.5
        and meaning_errors <= 1
        and tense_errors <= 1
        and gender_errors <= 1
    )
    return {
        "passed": passed,
        "averages": averages,
        "meaning_errors": meaning_errors,
        "meaning_candidates": meaning_candidates,
        "style_notes": style_notes,
        "tense_errors": tense_errors,
        "gender_errors": gender_errors,
        "scored_samples": len(scored),
        "warnings": warnings,
    }


def _confirmation_prompt(
    samples: List[Dict[str, Any]], flagged: List[Dict[str, Any]]
) -> str:
    by_id = {str(sample.get("id")): sample for sample in samples}
    lines = [
        "You are verifying candidate factual errors flagged by a first pass.",
        "For each pair, decide how many factual errors are confirmed. A factual error changes what the reader understands happened: a wrong referent, an inverted relation, a dropped or added proposition that changes an event, or a wrong number, name or term.",
        "A weaker image, a calque, lost irony, register, or a nuance that is still understandable is NOT a factual error. Do not confirm those. The first pass often over-counts; be strict.",
        'Return ONLY JSON: {"items":[{"id":"...","confirmed_errors":0,"reason":"short Portuguese"}]}',
        "Do not use markdown fences. Do not add commentary outside the JSON.",
        "",
    ]
    for item in flagged:
        sample = by_id.get(str(item.get("id")))
        if not sample:
            continue
        lines.extend(
            [
                f"ID: {item.get('id')}",
                f"FIRST-PASS NOTE: {item.get('notes', '')}",
                "SOURCE:",
                sample["source"],
                "",
                "TARGET:",
                sample["target"],
                "",
            ]
        )
    return "\n".join(lines)


def _apply_meaning_confirmation(
    items: List[Dict[str, Any]], confirmed: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Replace candidate meaning errors with the confirmed count.

    A missing id keeps the candidate count: an incomplete confirmation must
    never turn a possible factual error into a pass.
    """
    for item in items:
        candidates = int(item.get("meaning_errors") or 0)
        if not candidates:
            continue
        entry = confirmed.get(str(item.get("id")))
        if entry is None:
            continue
        item["meaning_candidates"] = candidates
        item["meaning_errors"] = max(0, int(entry.get("confirmed_errors") or 0))
        item["meaning_confirmation"] = str(entry.get("reason") or "")
    return items


def _confirm_meaning_errors(
    samples: List[Dict[str, Any]],
    flagged: List[Dict[str, Any]],
    *,
    key: str,
    model: str,
    max_cloud_usd: float,
) -> tuple[Optional[Dict[str, Dict[str, Any]]], str, int, int, float]:
    """Second, narrow pass over the candidate factual errors.

    Returns ``(confirmed_by_id, error, input_tokens, output_tokens, cost)``.
    ``confirmed_by_id`` is None when the verification could not run; the
    caller then keeps the first-pass count instead of passing the book.
    """
    payload = {
        "model": model,
        "max_tokens": 1200,
        "thinking": {"type": "disabled"},
        "system": "You are a strict bilingual fact-checker. Confirm only changes in what the text says, not style.",
        "messages": [
            {"role": "user", "content": _confirmation_prompt(samples, flagged)}
        ],
    }
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        if not response.ok:
            return (
                None,
                f"HTTP {response.status_code}: {response.text[:400]}",
                0,
                0,
                0.0,
            )
        data = response.json()
    except Exception as exc:
        return (None, f"{type(exc).__name__}: {exc}", 0, 0, 0.0)

    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cost = input_tokens * 0.10 / 1_000_000 + output_tokens * 0.50 / 1_000_000
    if cost > max_cloud_usd:
        return (
            None,
            f"confirmation cost ${cost:.4f} exceeds cap ${max_cloud_usd:.4f}",
            input_tokens,
            output_tokens,
            cost,
        )

    content = ""
    for block in data.get("content") or []:
        if block.get("type") == "text":
            content += block.get("text", "")
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return (None, "confirmation returned no JSON", input_tokens, output_tokens, cost)
    try:
        parsed = json.loads(content[start : end + 1])
    except ValueError as exc:
        return (
            None,
            f"invalid confirmation JSON: {exc}",
            input_tokens,
            output_tokens,
            cost,
        )
    entries = parsed.get("items") or []
    confirmed = {
        str(entry.get("id")): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("id")
    }
    if not confirmed:
        return (
            None,
            "confirmation returned no items",
            input_tokens,
            output_tokens,
            cost,
        )
    return (confirmed, "", input_tokens, output_tokens, cost)


def _cloud_audit(
    samples: List[Dict[str, Any]],
    *,
    max_cloud_usd: float,
    book_title: str,
) -> Dict[str, Any]:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5").strip()
    if not key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY missing", "passed": False}
    if not samples:
        return {"ok": False, "error": "no aligned samples", "passed": False}

    payload = {
        "model": model,
        "max_tokens": 2600,
        "thinking": {"type": "disabled"},
        "system": "You are a meticulous bilingual literary editor. Judge only the supplied source and target.",
        "messages": [{"role": "user", "content": _cloud_prompt(samples)}],
    }
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        if not response.ok:
            return {
                "ok": False,
                "error": f"HTTP {response.status_code}: {response.text[:800]}",
                "passed": False,
            }
        data = response.json()
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "passed": False}

    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cost = input_tokens * 0.10 / 1_000_000 + output_tokens * 0.50 / 1_000_000
    if cost > max_cloud_usd:
        return {
            "ok": False,
            "error": f"cloud audit cost ${cost:.4f} exceeds cap ${max_cloud_usd:.4f}",
            "passed": False,
            "cost_usd": round(cost, 6),
        }

    content = ""
    for block in data.get("content") or []:
        if block.get("type") == "text":
            content += block.get("text", "")
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return {"ok": False, "error": "cloud audit returned no JSON", "passed": False}
    try:
        parsed = json.loads(content[start : end + 1])
    except ValueError as exc:
        return {"ok": False, "error": f"invalid cloud JSON: {exc}", "passed": False}

    items = parsed.get("items") or []
    scored = [
        item
        for item in items
        if isinstance(item, dict) and not item.get("alignment_suspect")
    ]
    if len(scored) < 3:
        return {
            "ok": False,
            "error": "fewer than three aligned scored samples",
            "passed": False,
            "items": items,
            "cost_usd": round(cost, 6),
        }

    verdict = _cloud_verdict(items)
    total_input = input_tokens
    total_output = output_tokens
    total_cost = cost
    flagged = [
        item
        for item in items
        if isinstance(item, dict) and int(item.get("meaning_errors") or 0) > 0
    ]
    if flagged:
        confirmed, error, extra_in, extra_out, extra_cost = _confirm_meaning_errors(
            samples,
            flagged,
            key=key,
            model=model,
            max_cloud_usd=max(0.0, max_cloud_usd - cost),
        )
        total_input += extra_in
        total_output += extra_out
        total_cost += extra_cost
        if confirmed is None:
            verdict["warnings"].append(f"meaning confirmation unavailable: {error}")
        else:
            _apply_meaning_confirmation(items, confirmed)
            verdict = _cloud_verdict(items)
            verdict["meaning_confirmation"] = "applied"
    result = {
        "ok": True,
        "model": model,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cost_usd": round(total_cost, 6),
        **verdict,
        "items": items,
        "summary": parsed.get("summary", ""),
    }
    _record_cost(book_title, model, total_input, total_output, total_cost)
    return result


def _record_cost(book_title: str, model: str, input_tokens: int, output_tokens: int, cost: float) -> None:
    row = {
        "timestamp": _utc(),
        "provider": "anthropic",
        "model": model,
        "book": book_title,
        "stage": "auto-audit",
        "prompt_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
        "estimated": False,
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _resolve_target(report: Dict[str, Any], book: Any, outputs: Path) -> Path:
    for key in ("refined_output", "fixed_output", "output"):
        value = str(report.get(key) or "").strip()
        if value and Path(value).exists():
            return Path(value)
    name = f"{book.title} (pt-BR).epub"
    return outputs / name


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-id", type=int, required=True)
    parser.add_argument("--job-id", type=int, default=0)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "literary_queue.db")
    parser.add_argument("--outputs", type=Path, default=ROOT / "translated_files")
    parser.add_argument("--max-cloud-usd", type=float, default=0.05)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--no-cloud", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    store = QueueStore(args.db)
    book = store.get_book(args.book_id)
    job = store.get_job(args.job_id) if args.job_id else store.latest_job(args.book_id)
    store.close()
    if not book or not job:
        raise SystemExit("book or job not found")

    report: Dict[str, Any] = {}
    if args.report and args.report.exists():
        report = json.loads(args.report.read_text(encoding="utf-8"))
    target = _resolve_target(report, book, args.outputs)
    source = Path(book.source_path)
    if not source.exists() or not target.exists():
        raise SystemExit(f"source or target missing: source={source} target={target}")

    source_text, source_files = _epub_text(source)
    target_text, target_files = _epub_text(target)
    samples = _sample_pairs(source_files, target_files, limit=max(3, args.samples))
    glossary_path = str((report.get("assets") or {}).get("glossary_host") or "").strip()
    resolved = _resolve_terms(
        book,
        Path(glossary_path) if glossary_path else None,
    )
    terms = _term_audit(
        book,
        source_text,
        target_text,
        glossary_path=Path(glossary_path) if glossary_path else None,
        resolved=resolved,
    )
    per_file = scan_book(source, target, resolved["terms"])
    metrics = _text_metrics(source_text, target_text)
    glossary_hash = None
    glossary_hash_mismatch = False
    if glossary_path and Path(glossary_path).exists():
        glossary_file = Path(glossary_path)
        sidecar = glossary_file.with_suffix(".sha256")
        glossary_hash = hashlib.sha256(glossary_file.read_bytes()).hexdigest()
        if sidecar.exists():
            expected = sidecar.read_text(encoding="utf-8").strip()
            glossary_hash_mismatch = bool(expected and expected != glossary_hash)

    validation = report.get("validation") or {}
    epubcheck = report.get("epubcheck") or {}
    gate_ok = bool(report.get("gate_passed"))
    epub_ok = bool(validation.get("passed")) and int(epubcheck.get("errors") or 0) == 0
    if not report:
        gate_ok = False
        epub_ok = False

    cloud: Dict[str, Any] = {"ok": False, "passed": False, "error": "not run"}
    if not args.no_cloud:
        cloud = _cloud_audit(samples, max_cloud_usd=args.max_cloud_usd, book_title=book.title)
    else:
        cloud = {"ok": True, "passed": True, "error": "cloud audit disabled"}

    reasons: List[str] = []
    if not gate_ok or not epub_ok:
        reasons.append("queue gate (validation/EPUBCheck) failed or report missing")
    if not terms.get("ok"):
        reasons.append(f"glossary audit failed: {terms.get('error')}")
    elif float(terms.get("coverage") or 0) < 0.90:
        reasons.append(f"glossary coverage {terms.get('coverage')} < 0.90")
    if terms.get("forbidden_hits"):
        reasons.append(f"{len(terms['forbidden_hits'])} forbidden rendering(s) found")
    if terms.get("drift"):
        reasons.append(f"{len(terms['drift'])} glossary term(s) drifted after the run")
    if glossary_hash_mismatch:
        reasons.append("compiled glossary snapshot changed after the run")
    if metrics.get("pt_pt_per_100k", 0) > 50:
        reasons.append(f"pt-PT markers {metrics['pt_pt_per_100k']} per 100k > 50")
    if metrics.get("english_leakage") is not None and metrics["english_leakage"] > 0.01:
        reasons.append(f"English leakage {metrics['english_leakage']} > 0.01")
    if metrics.get("repetition_ratio") is not None and metrics["repetition_ratio"] > 0.05:
        reasons.append(f"repetition {metrics['repetition_ratio']} > 0.05")
    if metrics.get("length_ratio") is not None and not 0.80 <= metrics["length_ratio"] <= 1.20:
        reasons.append(f"length ratio {metrics['length_ratio']} outside 0.80-1.20")
    for reason in per_file["gate"]["reasons"]:
        reasons.append(f"per-file: {reason}")
    if not cloud.get("passed"):
        if cloud.get("ok"):
            averages = cloud.get("averages") or {}
            reasons.append(
                "cloud audit failed: "
                f"prose {averages.get('prose')}, fidelity {averages.get('fidelity')}, "
                f"naturalness {averages.get('naturalness')}, "
                f"meaning {cloud.get('meaning_errors')}/{cloud.get('meaning_candidates')} confirmed, "
                f"style {cloud.get('style_notes')}, "
                f"tense {cloud.get('tense_errors')}, gender {cloud.get('gender_errors')}"
            )
        else:
            reasons.append(f"cloud audit failed: {cloud.get('error', 'unknown')}")

    passed = not reasons
    audit = {
        "created_at": _utc(),
        "book": book.title,
        "book_id": book.id,
        "job_id": job.get("id"),
        "model": book.model,
        "provider": book.provider,
        "source": str(source),
        "target": str(target),
        "report": str(args.report) if args.report else "",
        "passed": passed,
        "reasons": reasons,
        "warnings": cloud.get("warnings") or [],
        "gate": {
            "queue_gate": gate_ok,
            "epubcheck_errors": int(epubcheck.get("errors") or 0),
            "validation_blocking": validation.get("blocking"),
        },
        "terms": terms,
        "metrics": metrics,
        "samples": samples,
        "per_file": {
            "schema": per_file["schema"],
            "schema_version": per_file["schema_version"],
            "totals": per_file["totals"],
            "gate": per_file["gate"],
            "offenders": per_file["offenders"],
        },
        "cloud": cloud,
        "glossary_hash": glossary_hash,
        "glossary_hash_mismatch": glossary_hash_mismatch,
    }

    out_dir = args.out or (AUDIT_ROOT / f"{_slug(book.title)}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "per_file.json").write_text(
        json.dumps(per_file, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "samples.jsonl").write_text(
        "\n".join(json.dumps(sample, ensure_ascii=False) for sample in samples) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# Audit: {book.title}",
        "",
        f"- Result: **{'PASS' if passed else 'FAIL'}**",
        f"- Generated: {audit['created_at']}",
        f"- Model: `{book.model}` ({book.provider})",
        f"- Target: `{target}`",
        "",
        "## Gates",
        "",
        f"- Queue validation/EPUBCheck: {gate_ok}/{epub_ok} (errors {audit['gate']['epubcheck_errors']}, blocking {audit['gate']['validation_blocking']})",
        f"- Glossary coverage: {terms.get('coverage')} ({terms.get('hits')}/{terms.get('eligible')}); forbidden hits: {len(terms.get('forbidden_hits') or [])}",
        f"- pt-PT markers: {metrics.get('pt_pt_per_100k')} per 100k",
        f"- English leakage: {metrics.get('english_leakage')}",
        f"- Repetition: {metrics.get('repetition_ratio')}",
        f"- Length ratio: {metrics.get('length_ratio')}",
        f"- Cloud samples: {cloud.get('scored_samples')} scored; averages {cloud.get('averages')}; meaning errors {cloud.get('meaning_errors')}/{cloud.get('meaning_candidates')} confirmed; style notes {cloud.get('style_notes')} (advisory)",
        f"- Cloud prose: {(cloud.get('averages') or {}).get('prose')}; tense errors {cloud.get('tense_errors')}; gender errors {cloud.get('gender_errors')}",
        "",
        "## Reasons",
        "",
    ]
    if reasons:
        lines.extend(f"- {reason}" for reason in reasons)
    else:
        lines.append("- All gates passed.")
    warnings = cloud.get("warnings") or []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    totals = per_file["totals"]
    offenders = per_file["offenders"]
    lines.extend(
        [
            "",
            "## Per-file coverage",
            "",
            f"- XHTML files scanned: {totals['files']} (100%); paired with source: {totals['files_with_source']}",
            f"- Words: {totals['words']}; forbidden hits: {totals['forbidden_hits']}",
            f"- Glossary file pairs: {totals['glossary_hits']}/{totals['glossary_pairs']} ({totals['glossary_coverage']})",
            f"- pt-PT: {totals['pt_pt']} total, {totals['pt_pt_blocking']} blocking ({totals['pt_pt_blocking_per_100k']} per 100k)",
            f"- English leakage: {totals['english_leakage']}; repetition: {totals['repetition_ratio']}; length ratio: {totals['length_ratio']}",
            f"- Dropcap issues: {totals['dropcap_issues']}; all-caps hits: {totals['caps_hits']}; truncated terms: {totals['truncated_terms']}; missing targets: {totals['missing_targets']}",
        ]
    )
    for title, key, formatter in [
        ("Glossary offenders", "glossary_missing", lambda item: f"{item['file']}: {item['source']} -> {item['target']} ({item.get('confidence') or 'unrated'})"),
        ("pt-PT offenders", "pt_pt", lambda item: f"{item['file']}: {item['blocking']} blocking, {item['count']} total ({item['blocking_per_100k']} per 100k)"),
        ("Leakage offenders", "english_leakage", lambda item: f"{item['file']}: {item['ratio']}"),
        ("Repetition offenders", "repetition", lambda item: f"{item['file']}: {item['ratio']}"),
        ("Length-ratio offenders", "length_ratio", lambda item: f"{item['file']}: {item['ratio']}"),
        ("Dropcap offenders", "dropcap", lambda item: f"{item['file']}: {item['message']}"),
        ("All-caps offenders", "caps", lambda item: f"{item['file']}: {item['token']} ({item['kind']})"),
        ("Truncated-term offenders", "truncated", lambda item: f"{item['file']}: {item['token']} -> {item['expected']}"),
    ]:
        entries = offenders.get(key) or []
        if not entries:
            continue
        lines.extend(["", f"### {title}", ""])
        lines.extend(f"- {formatter(item)}" for item in entries[:5])
    lines.extend(["", "## Missing glossary targets", ""])
    for item in (terms.get("missing") or [])[:15]:
        lines.append(f"- {item['source']} -> {item['target']} ({item['category']})")
    lines.extend(["", "## Cloud notes", ""])
    for item in cloud.get("items") or []:
        lines.append(f"- {item.get('id')}: {item.get('notes', '')}")
    (out_dir / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"passed": passed, "audit": str(out_dir / "audit.json"), "reasons": reasons}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
