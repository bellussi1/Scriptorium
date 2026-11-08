"""Source-aware selective refinement.

The upstream refinement pass never sees the source and asks the model to
rewrite an “amateur” draft. This module is the replacement design: the model
receives source, draft, the specific flagged issues, glossary and style, and is
allowed only a bounded repair. A deterministic guard keeps the draft when the
repair is unsafe.

It is a library, not yet wired into the upstream job runner.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .models import CompiledResources, Severity, ValidationIssue
from .validation import (
    _placeholders,
    detect_language,
    numbers_compatible,
    numeric_tokens,
    target_present,
)

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_EN_STOPWORDS = {
    "the", "and", "of", "to", "in", "that", "he", "she", "it", "was", "were",
    "with", "for", "on", "at", "but", "his", "her", "they", "had",
    "you", "not", "this", "from", "have", "by", "be", "which", "or", "an",
}


@dataclass
class RefinementIssue:
    code: str
    message: str
    location: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message, "location": self.location}


@dataclass
class GuardResult:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    similarity: float = 0.0
    edit_ratio: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reasons": self.reasons,
            "similarity": round(self.similarity, 4),
            "edit_ratio": round(self.edit_ratio, 4),
        }


@dataclass
class RefinementResult:
    text: str
    accepted: bool
    guard: GuardResult
    messages: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "accepted": self.accepted,
            "guard": self.guard.to_dict(),
            "messages": self.messages,
        }


SYSTEM_PROMPT = """You are a bilingual literary editor working from English into Brazilian Portuguese. You will receive the English source, a Portuguese draft, and a list of specific problems found by a validator.

Your task is to repair only the listed problems. You are not rewriting the passage for taste.

Hard rules:
1. Preserve the meaning, implication, ambiguity and deliberate repetition of the source.
2. Preserve names, invented terms, numbers, dates and forms of address exactly as the glossary says.
3. Do not add information, explanations, notes or new images.
4. Do not remove a clause, sentence or named entity.
5. Keep the narrator's person, gender, distance and register.
6. Prefer the smallest edit that fixes the listed problem.
7. If a problem cannot be fixed without guessing, leave the draft and do not invent a solution.
8. Output only the revised Brazilian Portuguese text. No commentary, no tags, no markdown.
"""


def _issue_lines(issues: Sequence[RefinementIssue]) -> str:
    if not issues:
        return "- (no specific issue; only correct a clear, demonstrable error)"
    return "\n".join(f"- {issue.code}: {issue.message}" for issue in issues)


def _glossary_lines(compiled: Optional[CompiledResources]) -> str:
    if compiled is None:
        return ""
    lines = []
    for term in compiled.glossary.terms:
        groups: Dict[str, List[str]] = {}
        order: List[str] = []
        for form in term.source_forms():
            target = term.target_for_form(form)
            if not target:
                continue
            key = target.casefold()
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(form)
        for key in order:
            forms = groups[key]
            target = term.target_for_form(forms[0])
            line = f"- {', '.join(forms)} -> {target}"
            if term.forbidden:
                line += f" (never: {', '.join(term.forbidden)})"
            lines.append(line)
    return "\n".join(lines)


def build_source_aware_messages(
    source: str,
    draft: str,
    issues: Sequence[RefinementIssue],
    *,
    compiled: Optional[CompiledResources] = None,
    style: str = "",
) -> List[Dict[str, str]]:
    """Build a chat prompt that includes the source, draft and issue list."""
    glossary = _glossary_lines(compiled)
    style_block = f"\n# STYLE\n\n{style.strip()}\n" if style and style.strip() else ""
    glossary_block = f"\n# GLOSSARY\n\n{glossary}\n" if glossary else ""
    user = (
        "# ENGLISH SOURCE\n\n"
        f"{source.strip()}\n\n"
        "# PORTUGUESE DRAFT\n\n"
        f"{draft.strip()}\n\n"
        "# FLAGGED ISSUES\n\n"
        f"{_issue_lines(issues)}\n"
        f"{glossary_block}{style_block}\n"
        "Return only the revised Brazilian Portuguese text."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def apply_guard(
    source: str,
    draft: str,
    revised: str,
    *,
    compiled: Optional[CompiledResources] = None,
    max_edit_ratio: float = 0.35,
    min_length_ratio: float = 0.60,
    max_length_ratio: float = 1.55,
) -> GuardResult:
    """Reject a refinement that changes too much or loses required content."""
    reasons: List[str] = []
    if not (revised or "").strip():
        return GuardResult(False, ["empty revised text"], 0.0, 1.0)
    if not (draft or "").strip():
        return GuardResult(False, ["empty draft"], 0.0, 1.0)

    similarity = difflib.SequenceMatcher(None, draft, revised).ratio()
    edit_ratio = 1.0 - similarity
    if edit_ratio > max_edit_ratio:
        reasons.append(f"edit ratio {edit_ratio:.2f} exceeds {max_edit_ratio:.2f}")

    ratio = len(revised) / max(1, len(draft))
    if ratio < min_length_ratio or ratio > max_length_ratio:
        reasons.append(f"length ratio {ratio:.2f} outside [{min_length_ratio}, {max_length_ratio}]")

    source_numbers = numeric_tokens(source)
    revised_numbers = numeric_tokens(revised)
    if not numbers_compatible(source_numbers, revised_numbers):
        missing = source_numbers - revised_numbers
        if missing:
            reasons.append(f"source numbers missing: {dict(missing)}")
        introduced = revised_numbers - source_numbers
        if introduced:
            reasons.append(f"numbers not in source: {dict(introduced)}")

    if _placeholders(source) != _placeholders(revised):
        reasons.append("placeholder/tag multiset differs from source")

    if compiled is not None:
        for term in compiled.glossary.terms:
            matched_forms = [
                form for form in term.source_forms()
                if re.search(r"\b" + re.escape(form) + r"\b", source, re.IGNORECASE)
            ]
            for form in matched_forms:
                expected = term.target_for_form(form)
                if expected and not target_present(expected, revised):
                    reasons.append(f"glossary target missing: {form} -> {expected}")
            for forbidden in term.forbidden:
                if forbidden and forbidden.casefold() in revised.casefold():
                    reasons.append(f"forbidden rendering present: {forbidden}")

    words = re.findall(r"[^\W\d_]+", revised, re.UNICODE)
    if words:
        leakage = sum(1 for word in words if word.casefold() in _EN_STOPWORDS) / len(words)
        if leakage > 0.06:
            reasons.append(f"English leakage {leakage:.3f} above 0.06")

    return GuardResult(not reasons, reasons, similarity, edit_ratio)


def refine_with_guard(
    source: str,
    draft: str,
    issues: Sequence[RefinementIssue],
    generate: Callable[[List[Dict[str, str]]], str],
    *,
    compiled: Optional[CompiledResources] = None,
    style: str = "",
    max_edit_ratio: float = 0.35,
) -> RefinementResult:
    """Call a model and return the revised text only if the guard accepts it.

    ``generate`` is injected so the component is testable without a provider.
    The caller owns retries and logging.
    """
    messages = build_source_aware_messages(source, draft, issues, compiled=compiled, style=style)
    revised = (generate(messages) or "").strip()
    guard = apply_guard(source, draft, revised, compiled=compiled, max_edit_ratio=max_edit_ratio)
    return RefinementResult(
        text=revised if guard.ok else draft,
        accepted=guard.ok,
        guard=guard,
        messages=messages,
    )
