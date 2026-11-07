"""Contextual glossary selection and prompt rendering.

The upstream application already has a per-chunk glossary filter. This module
adds the editorial layer it does not have: aliases, forbidden renderings,
book-order visibility (no terms from later volumes) and a token budget instead
of a fixed entry count.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import CompiledResources, Term

_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        # Conservative fallback for environments without tiktoken.
        return max(1, len(text) // 4)


def _is_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _count_form(form: str, text: str, case_sensitive: bool) -> int:
    if not form or not text:
        return 0
    if _is_cjk(form) or not (form[0].isalnum() or form[-1].isalnum()):
        return (text if case_sensitive else text.casefold()).count(form if case_sensitive else form.casefold())
    flags = 0 if case_sensitive else re.IGNORECASE
    return len(re.findall(r"\b" + re.escape(form) + r"\b", text, flags))


@dataclass
class SelectedTerm:
    term: Term
    matched_forms: List[str]
    occurrences: int
    estimated_tokens: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.term.source,
            "target": self.term.effective_target(),
            "matched_forms": self.matched_forms,
            "occurrences": self.occurrences,
            "category": self.term.category,
            "gender": self.term.gender,
            "forbidden": self.term.forbidden,
            "estimated_tokens": self.estimated_tokens,
        }


def select_terms(
    chunk: str,
    compiled: CompiledResources,
    *,
    max_entries: int = 50,
    max_tokens: int = 900,
    case_sensitive: bool = False,
) -> List[SelectedTerm]:
    """Select the glossary entries that matter for one chunk, within a token budget."""
    candidates: List[SelectedTerm] = []
    for term in compiled.glossary.terms:
        # Short forms may need a different target from the full name. Group the
        # surface forms by target and emit one prompt entry per group.
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
            matched = [form for form in forms if _count_form(form, chunk, case_sensitive)]
            if not matched:
                continue
            occurrences = sum(_count_form(form, chunk, case_sensitive) for form in matched)
            display = ", ".join(forms)
            rendered = f"  - {display} -> {target}"
            if term.category or term.gender:
                hints = ", ".join(x for x in (term.category, term.gender) if x)
                rendered += f"  [{hints}]"
            if term.forbidden:
                rendered += f"  [do not use: {', '.join(term.forbidden)}]"
            prompt_term = replace(
                term,
                source=forms[0],
                target=target,
                aliases=forms[1:],
                alias_targets={},
            )
            candidates.append(
                SelectedTerm(
                    term=prompt_term,
                    matched_forms=matched,
                    occurrences=occurrences,
                    estimated_tokens=estimate_tokens(rendered),
                )
            )

    candidates.sort(
        key=lambda item: (
            item.occurrences,
            max((len(form) for form in item.matched_forms), default=0),
            item.term.approved,
            item.term.confidence == "confirmed",
        ),
        reverse=True,
    )

    selected: List[SelectedTerm] = []
    used_tokens = 0
    for item in candidates:
        if len(selected) >= max_entries:
            break
        if selected and used_tokens + item.estimated_tokens > max_tokens:
            continue
        selected.append(item)
        used_tokens += item.estimated_tokens
    return selected


def build_glossary_block(selected: Sequence[SelectedTerm], *, target_language: str = "Brazilian Portuguese") -> str:
    if not selected:
        return ""
    lines = [
        "# GLOSSARY - REQUIRED TRANSLATIONS",
        "",
        "MANDATORY: use these EXACT renderings whenever the source term appears.",
        "Do NOT paraphrase, transliterate differently, or invent alternatives.",
        "Bracketed hints describe the entity; they are not part of the translation.",
        "When a forbidden rendering is listed, never use it, even if it sounds natural.",
        "",
    ]
    for item in selected:
        term = item.term
        display = ", ".join(term.source_forms())
        hints = ", ".join(x for x in (term.category, term.gender) if x)
        line = f"  - {display} -> {term.effective_target()}"
        if hints:
            line += f"  [{hints}]"
        if term.forbidden:
            line += f"  [forbidden: {', '.join(term.forbidden)}]"
        lines.append(line)
    return "\n".join(lines) + "\n"


def build_cast_block(compiled: CompiledResources, max_entries: int = 80) -> str:
    entries = [
        term
        for term in compiled.glossary.terms
        if term.gender in {"male", "female"}
    ][:max_entries]
    if not entries:
        return ""
    lines = [
        "# CAST - CHARACTER GENDERS",
        "",
        "MANDATORY: each entity below has a fixed gender for the entire work.",
        "Use pronouns and gendered agreement matching the list, even when the source passage omits the subject.",
        "Never switch an entity's gender between passages.",
        "",
    ]
    for term in entries:
        label = f"{term.source} ({term.effective_target()})" if term.effective_target() != term.source else term.source
        lines.append(f"  - {label} — {term.gender}")
    return "\n".join(lines) + "\n"


def build_prompt_fragment(chunk: str, compiled: CompiledResources, *, max_tokens: int = 900) -> str:
    selected = select_terms(chunk, compiled, max_tokens=max_tokens)
    glossary = build_glossary_block(selected)
    cast = build_cast_block(compiled)
    if not glossary and not cast:
        return ""
    if not glossary:
        return cast
    if not cast:
        return glossary
    return f"{cast}\n{glossary}"
