"""Deterministic best-of-N selection for literary segments.

A second sample is only useful if the caller can choose between candidates
without asking the model to judge itself. This module ranks candidates on
signals the pipeline already trusts: glossary/name recall, number recall,
length ratio, English leakage, repetition and high-confidence PT-BR errors.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .models import CompiledResources
from .ptbr import check_text
from .refine import _EN_STOPWORDS
from .validation import _placeholders, detect_language, numeric_tokens, target_present


def _words(text: str) -> List[str]:
    return re.findall(r"[^\W\d_]+", text or "", re.UNICODE)


def _repetition_ratio(text: str, n: int = 6) -> float:
    words = [word.casefold() for word in _words(text)]
    if len(words) < n * 2:
        return 0.0
    grams = [tuple(words[index : index + n]) for index in range(len(words) - n + 1)]
    if not grams:
        return 0.0
    most_common = Counter(grams).most_common(1)[0][1]
    return most_common / len(grams)


def _number_recall(source: str, candidate: str) -> float:
    expected = numeric_tokens(source)
    if not expected:
        return 1.0
    present = numeric_tokens(candidate)
    matched = sum(min(count, present.get(token, 0)) for token, count in expected.items())
    return matched / sum(expected.values())


def _glossary_recall(source: str, candidate: str, compiled: Optional[CompiledResources]) -> float:
    if compiled is None or not compiled.glossary.terms:
        return 1.0
    required = []
    for term in compiled.glossary.terms:
        matched = [
            form
            for form in term.source_forms()
            if re.search(r"\b" + re.escape(form) + r"\b", source, re.IGNORECASE)
        ]
        if not matched:
            continue
        expected = term.target_for_form(matched[0])
        if expected:
            required.append(expected)
    if not required:
        return 1.0
    score = 0.0
    for expected in required:
        if expected in candidate:
            score += 1.0
        elif target_present(expected, candidate):
            # Case matters for names and invented terms; a lowercase match is
            # still usable but should not outrank the glossary's exact form.
            score += 0.6
    return score / len(required)


@dataclass
class Candidate:
    index: int
    text: str
    label: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    eligible: bool = True
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
            "text": self.text,
            "score": round(self.score, 4),
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
        }


def score_candidate(
    source: str,
    candidate: str,
    *,
    index: int = 0,
    label: str = "",
    compiled: Optional[CompiledResources] = None,
) -> Candidate:
    source_words = max(1, len(_words(source)))
    candidate_words = len(_words(candidate))
    length_ratio = candidate_words / source_words
    leakage = (
        sum(1 for word in _words(candidate) if word.casefold() in _EN_STOPWORDS)
        / max(1, candidate_words)
    )
    repetition = _repetition_ratio(candidate)
    numbers = _number_recall(source, candidate)
    names = _glossary_recall(source, candidate, compiled)
    grammar_errors = sum(1 for issue in check_text(candidate) if issue.severity == "error")
    language = detect_language(candidate)
    placeholders_match = _placeholders(source) == _placeholders(candidate)

    reasons: List[str] = []
    if not candidate.strip():
        reasons.append("empty")
    if language == "en":
        reasons.append("detected_as_english")
    if not placeholders_match:
        reasons.append("placeholder_mismatch")
    if length_ratio < 0.50 or length_ratio > 1.80:
        reasons.append("length_ratio_out_of_range")
    if names < 0.50:
        reasons.append("glossary_recall_below_0.50")

    length_score = max(0.0, 1.0 - abs(1.0 - length_ratio))
    leakage_score = max(0.0, 1.0 - min(leakage / 0.08, 1.0))
    repetition_score = max(0.0, 1.0 - min(repetition / 0.05, 1.0))
    grammar_score = max(0.0, 1.0 - min(grammar_errors / 3.0, 1.0))

    score = (
        0.35 * length_score
        + 0.25 * names
        + 0.20 * numbers
        + 0.10 * leakage_score
        + 0.05 * repetition_score
        + 0.05 * grammar_score
    )
    metrics = {
        "source_words": source_words,
        "candidate_words": candidate_words,
        "length_ratio": round(length_ratio, 4),
        "name_recall": round(names, 4),
        "number_recall": round(numbers, 4),
        "english_leakage": round(leakage, 4),
        "repetition": round(repetition, 4),
        "grammar_errors": grammar_errors,
        "language": language,
    }
    return Candidate(
        index=index,
        text=candidate,
        label=label,
        metrics=metrics,
        score=score,
        eligible=not reasons,
        reasons=reasons,
    )


def select_best(
    source: str,
    candidates: Sequence[str],
    *,
    compiled: Optional[CompiledResources] = None,
    labels: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Rank candidates and return the best eligible one.

    ``candidates`` must preserve generation order; ties are broken by that
    order so a seeded run is reproducible. If every candidate is ineligible,
    the highest-scoring one is still returned with ``fallback: true`` so the
    caller can decide whether to accept it.
    """
    if not candidates:
        raise ValueError("at least one candidate is required")
    labels = labels or [f"candidate-{index + 1}" for index in range(len(candidates))]
    scored = [
        score_candidate(
            source,
            text,
            index=index,
            label=labels[index] if index < len(labels) else f"candidate-{index + 1}",
            compiled=compiled,
        )
        for index, text in enumerate(candidates)
    ]
    eligible = [candidate for candidate in scored if candidate.eligible]
    ranked = sorted(scored, key=lambda item: (-item.score, item.index))
    best = ranked[0]
    return {
        "selected": best.to_dict(),
        "fallback": not any(candidate.eligible for candidate in scored),
        "eligible_count": len(eligible),
        "candidates": [candidate.to_dict() for candidate in ranked],
    }
