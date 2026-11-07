"""Deterministic validation for literary translations and EPUB output.

These checks are intentionally conservative. They flag a unit for review; they
never rewrite it. Probabilistic judgement (LLM-as-judge) belongs in the
benchmark, not in the save path.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import CompiledResources, Severity, ValidationIssue
from .epub import count_words, read_epub, validate_epub_structure

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
# Number words that are safe to compare across English and Portuguese. The
# Portuguese articles "um/uma" are deliberately excluded: they are far more
# often articles than numbers, and including them would create false matches.
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "thousand": 1000,
    "million": 1000000,
    "dois": 2,
    "duas": 2,
    "três": 3,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "catorze": 14,
    "quatorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "duzentas": 200,
    "trezentos": 300,
    "trezentas": 300,
    "quatrocentos": 400,
    "quatrocentas": 400,
    "quinhentos": 500,
    "quinhentas": 500,
    "seiscentos": 600,
    "seiscentas": 600,
    "setecentos": 700,
    "setecentas": 700,
    "oitocentos": 800,
    "oitocentas": 800,
    "novecentos": 900,
    "novecentas": 900,
    "mil": 1000,
    "milhão": 1000000,
    "milhao": 1000000,
    "milhões": 1000000,
    "milhoes": 1000000,
}
_NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(word) for word in sorted(_NUMBER_WORDS, key=len, reverse=True)
    ) + r")\b",
    re.IGNORECASE | re.UNICODE,
)
_PLACEHOLDER_PATTERNS = [
    re.compile(r"\[\[?\s*\d+\s*\]?\]"),
    re.compile(r"\[id\s*\d+\]", re.IGNORECASE),
    re.compile(r"\{\{?\s*[A-Za-z_][A-Za-z0-9_]*\s*\}?\}"),
]
_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_DROPCAP_RE = re.compile(
    r'<span[^>]*class="[^"]*\bdropcap\b[^"]*"[^>]*>(.*?)</span>(.{0,120})',
    re.IGNORECASE | re.DOTALL,
)
_DROPCAP_SELF_CLOSING_RE = re.compile(
    r'<span[^>]*class="[^"]*\bdropcap\b[^"]*"[^>]*/>',
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019\-][^\W\d_]+)*", re.UNICODE)

_EN_STOPWORDS = {
    "the", "and", "of", "to", "in", "that", "he", "she", "it", "was", "were",
    "with", "for", "on", "as", "at", "but", "his", "her", "they", "had",
    "you", "not", "this", "from", "have", "by", "be", "which", "or", "an",
}
_PT_STOPWORDS = {
    "o", "a", "os", "as", "de", "do", "da", "dos", "das", "e", "que", "em",
    "um", "uma", "para", "com", "não", "se", "por", "mais", "como", "mas",
    "ele", "ela", "eles", "elas", "foi", "eram", "ao", "à", "às", "dos",
}


def _split_paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _words(text: str) -> List[str]:
    return _WORD_RE.findall(text or "")


def _placeholders(text: str) -> Counter:
    counts: Counter = Counter()
    for pattern in _PLACEHOLDER_PATTERNS:
        for match in pattern.findall(text or ""):
            counts[match] += 1
    for match in _TAG_RE.findall(text or ""):
        counts[match] += 1
    return counts


def _numbers(text: str) -> Counter:
    return Counter(_NUMBER_RE.findall(text or ""))


def numeric_tokens(text: str) -> Counter:
    """Digit and number-word tokens normalized to a common value.

    ``3`` and ``três`` both become ``"3"`` so a guard does not reject a valid
    translation merely because the target spells the number out. The mapping is
    deliberately limited to unambiguous number words.
    """
    counts: Counter = Counter()
    for match in _NUMBER_RE.findall(text or ""):
        counts[match.replace(",", ".")] += 1
    for match in _NUMBER_WORD_RE.findall(text or ""):
        counts[str(_NUMBER_WORDS[match.casefold()])] += 1
    return counts


def detect_language(text: str) -> str:
    """Best-effort language code, with a deterministic fallback."""
    sample = (text or "").strip()
    if len(sample) < 40:
        return ""
    try:
        from langdetect import detect

        return detect(sample)
    except Exception:
        words = [word.casefold() for word in _words(sample)]
        if not words:
            return ""
        en = sum(1 for word in words if word in _EN_STOPWORDS) / len(words)
        pt = sum(1 for word in words if word in _PT_STOPWORDS) / len(words)
        if pt > en * 1.2 and pt > 0.03:
            return "pt"
        if en > pt * 1.2 and en > 0.03:
            return "en"
        return ""


def _repeated_ngrams(text: str, n: int = 6, minimum: int = 3) -> List[Tuple[str, int]]:
    words = [word.casefold() for word in _words(text)]
    if len(words) < n * minimum:
        return []
    counts: Counter = Counter(tuple(words[i:i + n]) for i in range(len(words) - n + 1))
    return [(" ".join(gram), count) for gram, count in counts.most_common(10) if count >= minimum]


def validate_pair(
    source: str,
    target: str,
    *,
    compiled: Optional[CompiledResources] = None,
    source_language: str = "en",
    target_language: str = "pt-BR",
    min_length_ratio: float = 0.65,
    max_length_ratio: float = 1.45,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if not (target or "").strip():
        return [ValidationIssue("target.empty", "Target unit is empty", Severity.CRITICAL)]
    source_words = _words(source)
    target_words = _words(target)
    if not source_words:
        return issues
    ratio = len(target_words) / len(source_words)
    if ratio < min_length_ratio or ratio > max_length_ratio:
        issues.append(
            ValidationIssue(
                "target.length_ratio",
                f"Length ratio {ratio:.2f} is outside [{min_length_ratio}, {max_length_ratio}]",
                Severity.WARNING,
                evidence={"source_words": len(source_words), "target_words": len(target_words), "ratio": round(ratio, 3)},
            )
        )

    source_paragraphs = _split_paragraphs(source)
    target_paragraphs = _split_paragraphs(target)
    if source_paragraphs and len(target_paragraphs) < len(source_paragraphs) * 0.9:
        issues.append(
            ValidationIssue(
                "target.paragraphs",
                f"Paragraph count dropped from {len(source_paragraphs)} to {len(target_paragraphs)}",
                Severity.ERROR,
                evidence={"source": len(source_paragraphs), "target": len(target_paragraphs)},
            )
        )

    source_numbers = numeric_tokens(source)
    target_numbers = numeric_tokens(target)
    missing_numbers = source_numbers - target_numbers
    if missing_numbers:
        issues.append(
            ValidationIssue(
                "target.numbers",
                f"Numbers missing from target: {dict(missing_numbers)}",
                Severity.ERROR,
                evidence={"missing": dict(missing_numbers)},
            )
        )

    source_placeholders = _placeholders(source)
    target_placeholders = _placeholders(target)
    if source_placeholders != target_placeholders:
        issues.append(
            ValidationIssue(
                "target.placeholders",
                "Placeholder/tag multiset differs from source",
                Severity.CRITICAL,
                evidence={"source": dict(source_placeholders), "target": dict(target_placeholders)},
            )
        )

    detected = detect_language(target)
    if target_language.lower().startswith("pt") and detected == "en":
        issues.append(
            ValidationIssue(
                "target.untranslated",
                "Target looks like English; long source spans may be untranslated",
                Severity.CRITICAL,
                evidence={"detected": detected},
            )
        )
    elif detected and detected != target_language[:2].lower() and detected not in {"pt", "en"}:
        issues.append(
            ValidationIssue(
                "target.language",
                f"Detected target language '{detected}' differs from '{target_language}'",
                Severity.WARNING,
                evidence={"detected": detected},
            )
        )

    if compiled is not None:
        for term in compiled.glossary.terms:
            forms = term.source_forms()
            if not any(re.search(r"\b" + re.escape(form) + r"\b", source, re.IGNORECASE) for form in forms):
                continue
            expected = term.effective_target()
            if expected and expected.casefold() not in target.casefold():
                issues.append(
                    ValidationIssue(
                        "glossary.missing_target",
                        f"Glossary term '{term.source}' is present in source but '{expected}' is absent from target",
                        Severity.ERROR if term.approved or term.confidence == "confirmed" else Severity.WARNING,
                        evidence={"source": term.source, "expected": expected, "confidence": term.confidence},
                    )
                )
            for forbidden in term.forbidden:
                if forbidden and forbidden.casefold() in target.casefold():
                    issues.append(
                        ValidationIssue(
                            "glossary.forbidden",
                            f"Forbidden rendering '{forbidden}' found in target",
                            Severity.ERROR,
                            evidence={"source": term.source, "forbidden": forbidden},
                        )
                    )

    source_repeats = {gram: count for gram, count in _repeated_ngrams(source)}
    for gram, count in _repeated_ngrams(target):
        if count > source_repeats.get(gram, 0) + 1:
            issues.append(
                ValidationIssue(
                    "target.repetition",
                    f"Repeated {len(gram.split())}-gram in target ({count} times): {gram[:80]}",
                    Severity.WARNING,
                    evidence={"count": count, "source_count": source_repeats.get(gram, 0)},
                )
            )
            break

    return issues


_PT_TRAILING_STOPWORDS = re.compile(
    r"\b(?:de|da|do|das|dos|um|uma|uns|umas|e|o|a|os|as|em|por|com|para)$",
    re.IGNORECASE,
)
_CAMEL_CONCAT = re.compile(r"[a-zà-öø-ÿ][A-ZÀ-ÖØ-Þ]")


def _toc_label_issues(source_label: str, target_label: str, href: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    source_label = (source_label or "").strip()
    target_label = (target_label or "").strip()
    if not target_label:
        return [ValidationIssue("epub.toc_empty", f"TOC label empty for {href}", Severity.ERROR, href)]
    source_words = _words(source_label)
    target_words = _words(target_label)
    if source_words and target_words:
        ratio = len(target_words) / len(source_words)
        if ratio < 0.45 or ratio > 2.2:
            issues.append(
                ValidationIssue(
                    "epub.toc_length",
                    f"TOC label for {href} changed length {ratio:.2f}x: '{target_label[:60]}'",
                    Severity.WARNING,
                    href,
                    {"source": source_label[:80], "target": target_label[:80], "ratio": round(ratio, 3)},
                )
            )
    # A label that glues two title fragments ("PrefácioUma", "CoelhoAlice")
    # is almost always a bug in the heading/anchor mapping, not a style choice.
    if " " not in target_label and len(target_label) > 10 and _CAMEL_CONCAT.search(target_label):
        issues.append(
            ValidationIssue(
                "epub.toc_concatenated",
                f"TOC label looks concatenated: '{target_label[:80]}'",
                Severity.ERROR,
                href,
                {"source": source_label[:80], "target": target_label[:80]},
            )
        )
    # The same bug can occur inside a title with spaces ("O Buraco do
    # CoelhoAlice"). "McCrae"/"MacLeod" are legitimate camel-case names, so
    # exclude those prefixes and downgrade the rest to a warning.
    for match in re.finditer(r"[a-zà-öø-ÿ]([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]{3,})", target_label):
        if match.group(1).startswith(("Mc", "Mac")):
            continue
        issues.append(
            ValidationIssue(
                "epub.toc_concatenated_word",
                f"TOC label contains a glued word: '{match.group(0)}'",
                Severity.WARNING,
                href,
                {"source": source_label[:80], "target": target_label[:80]},
            )
        )
        break
    # A translated heading should not end on a dangling function word.
    if _PT_TRAILING_STOPWORDS.search(target_label) and not _PT_TRAILING_STOPWORDS.search(source_label):
        issues.append(
            ValidationIssue(
                "epub.toc_truncated",
                f"TOC label ends on a dangling function word: '{target_label[:80]}'",
                Severity.WARNING,
                href,
                {"source": source_label[:80], "target": target_label[:80]},
            )
        )
    return issues


def _dropcap_html_issues(html: str, href: str) -> List[ValidationIssue]:
    """Catch silent content corruption around dropcap spans.

    A dropcap span must contain exactly the first character of the following
    word. Empty spans, full words and a source letter kept in front of a
    translated word are content errors, not layout warnings.
    """
    issues: List[ValidationIssue] = []
    for _match in _DROPCAP_SELF_CLOSING_RE.finditer(html or ""):
        issues.append(
            ValidationIssue(
                "epub.dropcap_empty",
                "dropcap span is empty; the first letter was lost",
                Severity.ERROR,
                href,
            )
        )
    for match in _DROPCAP_RE.finditer(html or ""):
        content = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        following = re.sub(r"<[^>]+>", "", match.group(2)).lstrip()
        if not content:
            issues.append(
                ValidationIssue(
                    "epub.dropcap_empty",
                    "dropcap span is empty; the first letter was lost",
                    Severity.ERROR,
                    href,
                )
            )
            continue
        if len(content) > 1 or "[" in content or "]" in content:
            issues.append(
                ValidationIssue(
                    "epub.dropcap_invalid",
                    f"dropcap span contains '{content[:40]}'; expected one character",
                    Severity.ERROR,
                    href,
                    {"content": content[:80]},
                )
            )
            continue
        if following and following[0].isupper():
            issues.append(
                ValidationIssue(
                    "epub.dropcap_letter",
                    f"dropcap '{content}' is not the first letter of the following "
                    f"word ('{following[:40]}')",
                    Severity.ERROR,
                    href,
                    {"dropcap": content, "following": following[:80]},
                )
            )
    return issues


def _dropcap_issues(target_epub: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    try:
        with zipfile.ZipFile(target_epub) as archive:
            for name in archive.namelist():
                if not name.lower().endswith((".xhtml", ".html", ".htm")):
                    continue
                html = archive.read(name).decode("utf-8", "replace")
                issues.extend(_dropcap_html_issues(html, name))
    except Exception:
        return issues
    return issues


def summarize_issues(issues: Sequence[ValidationIssue]) -> Dict[str, Any]:
    counts = Counter(issue.severity.value for issue in issues)
    blocking = counts.get(Severity.CRITICAL.value, 0) + counts.get(Severity.ERROR.value, 0)
    return {
        "passed": blocking == 0,
        "blocking": blocking,
        "counts": dict(counts),
        "issues": [issue.to_dict() for issue in issues],
    }


def validate_epub_pair(
    source_epub: str,
    target_epub: str,
    *,
    expected_language: str = "pt-BR",
) -> Dict[str, Any]:
    """Structural + coarse content validation of a translated EPUB."""
    issues: List[ValidationIssue] = []
    issues.extend(validate_epub_structure(target_epub))
    issues.extend(_dropcap_issues(target_epub))
    source = read_epub(source_epub, include_text=False)
    target = read_epub(target_epub, include_text=False)
    if source.issues:
        issues.extend(source.issues)
    if target.issues:
        issues.extend(target.issues)
    if source.document_count and target.document_count < source.document_count:
        issues.append(
            ValidationIssue(
                "epub.spine_count",
                f"Spine document count dropped from {source.document_count} to {target.document_count}",
                Severity.ERROR,
                evidence={"source": source.document_count, "target": target.document_count},
            )
        )
    elif source.document_count and target.document_count > source.document_count:
        issues.append(
            ValidationIssue(
                "epub.spine_extra",
                f"Spine gained {target.document_count - source.document_count} document(s); "
                "expected only the optional attribution page",
                Severity.WARNING,
                evidence={"source": source.document_count, "target": target.document_count},
            )
        )
    if source.toc and target.toc:
        if len(target.toc) < len(source.toc):
            issues.append(
                ValidationIssue(
                    "epub.toc_count",
                    f"TOC entries dropped from {len(source.toc)} to {len(target.toc)}",
                    Severity.WARNING,
                    evidence={"source": len(source.toc), "target": len(target.toc)},
                )
            )
        target_by_href = {entry.get("href", "").split("#")[0]: entry for entry in target.toc}
        for index, entry in enumerate(source.toc):
            source_href = entry.get("href", "").split("#")[0]
            target_entry = target_by_href.get(source_href)
            if target_entry is None and index < len(target.toc):
                target_entry = target.toc[index]
            if target_entry is None:
                issues.append(
                    ValidationIssue(
                        "epub.toc_missing",
                        f"TOC entry missing for {source_href or entry.get('title', '')}",
                        Severity.ERROR,
                        source_href,
                    )
                )
                continue
            issues.extend(_toc_label_issues(entry.get("title", ""), target_entry.get("title", ""), source_href))
    if target.language and not target.language.lower().startswith(expected_language[:2].lower()):
        issues.append(
            ValidationIssue(
                "epub.language",
                f"Target EPUB language is '{target.language}', expected '{expected_language}'",
                Severity.ERROR,
                evidence={"language": target.language},
            )
        )
    if source.word_count and target.word_count:
        ratio = target.word_count / source.word_count
        if ratio < 0.65 or ratio > 1.45:
            issues.append(
                ValidationIssue(
                    "epub.word_ratio",
                    f"Word count ratio {ratio:.2f} is outside [0.65, 1.45]",
                    Severity.ERROR,
                    evidence={"source": source.word_count, "target": target.word_count, "ratio": round(ratio, 3)},
                )
            )
    return {
        "source": source.to_dict(),
        "target": target.to_dict(),
        **summarize_issues(issues),
    }
