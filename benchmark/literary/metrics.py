"""Deterministic metrics for the literary benchmark.

These are triage signals, not a verdict. A high chrF can coexist with a
semantic inversion; a low chrF can coexist with a valid literary recreation.
The rubric and human/LLM review remain the decision layer.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Dict, Iterable, List, Optional

WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019\-][^\W\d_]+)*", re.UNICODE)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
EN_STOPWORDS = {
    "the", "and", "of", "to", "in", "that", "he", "she", "it", "was", "were",
    "with", "for", "on", "at", "but", "his", "her", "they", "had",
    "you", "not", "this", "from", "have", "by", "be", "which", "or", "an",
}


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", (text or "").strip())


def _words(text: str) -> List[str]:
    return WORD_RE.findall(_normalize(text))


def _char_ngrams(text: str, n: int) -> Counter:
    text = re.sub(r"\s+", " ", _normalize(text).casefold())
    return Counter(text[i:i + n] for i in range(max(0, len(text) - n + 1)))


def chrf(reference: str, hypothesis: str, max_n: int = 6, beta: float = 2.0) -> float:
    """Character n-gram F-beta, the standard chrF shape."""
    if not reference or not hypothesis:
        return 0.0
    precisions = []
    recalls = []
    for n in range(1, max_n + 1):
        ref = _char_ngrams(reference, n)
        hyp = _char_ngrams(hypothesis, n)
        if not ref or not hyp:
            continue
        overlap = sum((ref & hyp).values())
        precisions.append(overlap / sum(hyp.values()))
        recalls.append(overlap / sum(ref.values()))
    if not precisions:
        return 0.0
    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    if precision + recall == 0:
        return 0.0
    beta2 = beta * beta
    return round((1 + beta2) * precision * recall / (beta2 * precision + recall), 4)


def number_recall(source: str, output: str) -> Optional[float]:
    source_numbers = set(NUMBER_RE.findall(source or ""))
    if not source_numbers:
        return None
    output_numbers = set(NUMBER_RE.findall(output or ""))
    return round(len(source_numbers & output_numbers) / len(source_numbers), 4)


def name_recall(source: str, output: str, glossary: Optional[Dict[str, str]]) -> Optional[float]:
    if not glossary:
        return None
    expected = []
    for source_term, target_term in glossary.items():
        forms = [part.strip() for part in source_term.split("|") if part.strip()]
        if any(re.search(r"\b" + re.escape(form) + r"\b", source, re.IGNORECASE) for form in forms):
            expected.append(target_term)
    if not expected:
        return None
    present = sum(1 for term in expected if term.casefold() in (output or "").casefold())
    return round(present / len(expected), 4)


def english_leakage(output: str) -> float:
    words = [w.casefold() for w in _words(output)]
    if not words:
        return 0.0
    return round(sum(1 for w in words if w in EN_STOPWORDS) / len(words), 4)


def repetition_ratio(output: str, n: int = 6) -> float:
    words = [w.casefold() for w in _words(output)]
    if len(words) < n * 2:
        return 0.0
    grams = Counter(tuple(words[i:i + n]) for i in range(len(words) - n + 1))
    most_common = grams.most_common(1)[0][1]
    return round(most_common / max(1, len(grams)), 4)


def length_ratio(source: str, output: str) -> Optional[float]:
    source_words = _words(source)
    output_words = _words(output)
    if not source_words:
        return None
    return round(len(output_words) / len(source_words), 4)


def score_output(
    source: str,
    output: str,
    *,
    reference: str = "",
    glossary: Optional[Dict[str, str]] = None,
) -> Dict[str, float]:
    payload = {
        "length_ratio": length_ratio(source, output),
        "number_recall": number_recall(source, output),
        "name_recall": name_recall(source, output, glossary),
        "english_leakage": english_leakage(output),
        "repetition_ratio": repetition_ratio(output),
    }
    if reference:
        payload["chrf"] = chrf(reference, output)
    return payload
