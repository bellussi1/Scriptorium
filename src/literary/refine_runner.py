"""Source-aware selective refinement for text segments.

This is the production replacement for the upstream blind refinement: the model
sees the source segment, the draft, the exact flagged issue, the glossary and
the style, and the deterministic guard decides whether the revision is safe.
The caller owns the provider and the file format. EPUB writing is a separate
step; this module works on paragraph-aligned text.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests

from .models import CompiledResources
from .refine import RefinementIssue, _EN_STOPWORDS, refine_with_guard
from .validation import _placeholders, detect_language, numeric_tokens


@dataclass
class FlaggedSegment:
    index: int
    source: str
    draft: str
    issues: List[RefinementIssue] = field(default_factory=list)

    def to_report(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "issues": [issue.to_dict() for issue in self.issues],
            "source_chars": len(self.source),
            "draft_chars": len(self.draft),
        }


def split_segments(text: str) -> List[str]:
    """Split a document into paragraph-like segments without changing them."""
    return [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]


def _word_count(text: str) -> int:
    return len(re.findall(r"[^\W\d_]+", text or "", re.UNICODE))


def _glossary_issues(
    source: str, draft: str, compiled: Optional[CompiledResources]
) -> List[RefinementIssue]:
    if compiled is None:
        return []
    issues: List[RefinementIssue] = []
    expected_seen = set()
    for term in compiled.glossary.terms:
        matched = [
            form
            for form in term.source_forms()
            if re.search(r"\b" + re.escape(form) + r"\b", source, re.IGNORECASE)
        ]
        if not matched:
            continue
        for form in matched:
            expected = term.target_for_form(form)
            if not expected:
                continue
            key = expected.casefold()
            if key not in expected_seen and key not in draft.casefold():
                expected_seen.add(key)
                issues.append(
                    RefinementIssue(
                        "segment.glossary_missing",
                        f"glossary target missing for '{form}': expected '{expected}'",
                    )
                )
        for forbidden in term.forbidden:
            if forbidden and forbidden.casefold() in draft.casefold():
                issues.append(
                    RefinementIssue(
                        "segment.forbidden",
                        f"forbidden rendering present: '{forbidden}'",
                    )
                )
    return issues


def flags_for_segment(
    source: str,
    draft: str,
    *,
    compiled: Optional[CompiledResources] = None,
) -> List[RefinementIssue]:
    """Deterministic, segment-local reasons to refine a draft paragraph."""
    issues: List[RefinementIssue] = []
    if not (draft or "").strip():
        return [RefinementIssue("segment.empty", "draft segment is empty")]

    source_numbers = numeric_tokens(source)
    draft_numbers = numeric_tokens(draft)
    missing_numbers = source_numbers - draft_numbers
    if missing_numbers:
        issues.append(
            RefinementIssue(
                "segment.numbers",
                "source numbers missing: " + ", ".join(sorted(missing_numbers)),
            )
        )
    if _placeholders(source) != _placeholders(draft):
        issues.append(
            RefinementIssue("segment.placeholders", "placeholder/tag multiset differs")
        )

    source_words = _word_count(source)
    draft_words = _word_count(draft)
    if source_words >= 10:
        ratio = draft_words / max(1, source_words)
        if ratio < 0.50 or ratio > 2.00:
            issues.append(
                RefinementIssue(
                    "segment.length_ratio",
                    f"draft/source word ratio {ratio:.2f} outside [0.50, 2.00]",
                )
            )

    words = re.findall(r"[^\W\d_]+", draft, re.UNICODE)
    if words:
        leakage = sum(1 for word in words if word.casefold() in _EN_STOPWORDS) / len(words)
        if leakage > 0.08:
            issues.append(
                RefinementIssue(
                    "segment.english_leakage",
                    f"English stopword density {leakage:.3f} above 0.08",
                )
            )

    language = detect_language(draft)
    if language == "en":
        issues.append(
            RefinementIssue("segment.language", "draft is detected as English, not Portuguese")
        )

    issues.extend(_glossary_issues(source, draft, compiled))
    return issues


def find_flagged_segments(
    source_segments: Sequence[str],
    draft_segments: Sequence[str],
    *,
    compiled: Optional[CompiledResources] = None,
) -> List[FlaggedSegment]:
    """Pair segments by index and return only the ones with deterministic flags."""
    flagged: List[FlaggedSegment] = []
    for index, source in enumerate(source_segments):
        draft = draft_segments[index] if index < len(draft_segments) else ""
        issues = flags_for_segment(source, draft, compiled=compiled)
        if issues:
            flagged.append(
                FlaggedSegment(index=index, source=source, draft=draft, issues=issues)
            )
    return flagged


def generate_ollama(
    messages: List[Dict[str, str]],
    *,
    model: str,
    endpoint: str = "http://localhost:11434",
    temperature: float = 0.0,
    max_tokens: int = 800,
    num_ctx: int = 8192,
    timeout: int = 900,
) -> str:
    """Minimal Ollama chat client for the refinement pass."""
    response = requests.post(
        endpoint.rstrip("/") + "/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": num_ctx,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return ((data.get("message") or {}).get("content") or "").strip()


def refine_segments(
    flagged: Sequence[FlaggedSegment],
    generate: Callable[[List[Dict[str, str]]], str],
    *,
    compiled: Optional[CompiledResources] = None,
    style: str = "",
    max_edit_ratio: float = 0.35,
    limit: int = 0,
) -> Tuple[Dict[int, str], Dict[str, Any]]:
    """Refine flagged segments; return replacements and an auditable report."""
    replacements: Dict[int, str] = {}
    report: Dict[str, Any] = {
        "flagged": len(flagged),
        "attempted": 0,
        "accepted": 0,
        "rejected": 0,
        "skipped": 0,
        "segments": [],
    }
    selected = flagged[:limit] if limit and limit > 0 else flagged
    for segment in selected:
        entry: Dict[str, Any] = {"index": segment.index, "accepted": False}
        if not segment.draft.strip():
            report["skipped"] += 1
            entry["reason"] = "empty draft"
            report["segments"].append(entry)
            continue
        try:
            result = refine_with_guard(
                segment.source,
                segment.draft,
                segment.issues,
                generate,
                compiled=compiled,
                style=style,
                max_edit_ratio=max_edit_ratio,
            )
        except Exception as exc:  # provider/network failure: keep the draft
            report["rejected"] += 1
            entry["error"] = str(exc)
            report["segments"].append(entry)
            continue
        report["attempted"] += 1
        entry["guard"] = result.guard.to_dict()
        entry["issues"] = [issue.to_dict() for issue in segment.issues]
        if result.accepted:
            report["accepted"] += 1
            replacements[segment.index] = result.text
            entry["accepted"] = True
        else:
            report["rejected"] += 1
        report["segments"].append(entry)
    return replacements, report


def render_refined_text(
    draft_text: str, replacements: Dict[int, str]
) -> str:
    """Apply accepted replacements to the original draft, preserving separators."""
    parts = re.split(r"(\n\s*\n)", draft_text or "")
    segment_index = 0
    output: List[str] = []
    for part in parts:
        if re.fullmatch(r"\n\s*\n", part or ""):
            output.append(part)
            continue
        if not part.strip():
            output.append(part)
            continue
        output.append(replacements.get(segment_index, part.strip()))
        segment_index += 1
    return "".join(output).strip() + "\n"
