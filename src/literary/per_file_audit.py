"""Per-file deterministic audit for a translated EPUB.

The whole-book audit averages a defect over hundreds of thousands of words: one
corrupted chapter barely moves a global ratio. This module scans every XHTML
document on its own and reports the offenders by file, so the gate aggregates
without letting a local error dissolve into the total.

Two extraction details matter:

- inline tags are removed without inserting a space, so ``<span>C</span>HANTRY``
  stays one token instead of becoming ``C HANTRY``;
- short blocks are kept. The old paragraph filter dropped everything under five
  words, which is exactly the size of a dropcap line or a chapter opener.

No network access and no writes: this module only reads the two EPUBs.
"""
from __future__ import annotations

import html
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from benchmark.literary.metrics import english_leakage
from benchmark.literary.metrics import length_ratio as length_ratio_metric
from benchmark.literary.metrics import repetition_ratio
from src.literary.validation import _dropcap_html_issues, glossary_target_present

SCHEMA = "literary.per-file-audit"
SCHEMA_VERSION = "1.0"

# pt-PT markers. Each pattern is accent-specific on purpose: ``[aá]`` also
# matches the correct Brazilian form, which inflated the old count. ``vos`` is
# a valid object pronoun in pt-BR and must not be read as ``vós``.
PT_PT_PATTERNS = [
    r"\btu\b",
    r"\bdespertaste\b",
    r"\bquilómetros?\b",
    r"\bcontacto\b",
    r"\bde facto\b",
    r"\bdemónio\b",
    r"\ba dançar\b",
    r"\bestamos a\b",
    r"\bconvosco\b",
    r"\bcompreendes\b",
    r"\bencontrámos\b",
    r"\btravámos\b",
    r"\bouvistes\b",
    r"\bprémios?\b",
    r"\bFénix\b",
    r"\bse tinha deslocado\b",
    r"\bfazer-vos\b",
    r"\bvós\b",
]

# Only the forms that are European Portuguese and not a literary register
# choice block the book. ``vós``/``convosco``/``fazer-vos`` and the second
# person singular are archaic or dialectal in pt-BR; they are reported, not
# gated, because a formal character can use them on purpose.
PT_PT_BLOCKING_PATTERNS = [
    r"\bquilómetros?\b",
    r"\bcontacto\b",
    r"\bde facto\b",
    r"\bdemónio\b",
    r"\ba dançar\b",
    r"\bestamos a\b",
    r"\bencontrámos\b",
    r"\btravámos\b",
    r"\bprémios?\b",
    r"\bFénix\b",
    r"\bse tinha deslocado\b",
]

DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "glossary_coverage": 0.90,
    "glossary_file_floor": 0.80,
    "glossary_file_min_pairs": 10,
    "pt_pt_per_100k": 50.0,
    "pt_pt_file_per_100k": 100.0,
    "pt_pt_file_min_words": 500,
    "leakage": 0.01,
    "leakage_file": 0.02,
    "leakage_file_min_words": 500,
    "repetition": 0.05,
    "repetition_file": 0.10,
    "repetition_file_min_words": 500,
    "length_min": 0.80,
    "length_max": 1.20,
    "length_file_min_source_words": 200,
    "missing_target_min_words": 200,
}

_BLOCK_TAG_RE = re.compile(
    r"</?(?:p|div|h[1-6]|li|blockquote|section|article|header|footer|"
    r"tr|td|th|br|hr|figure|figcaption|pre|table|ul|ol|dl|dt|dd)\b[^>]*>",
    re.IGNORECASE,
)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019\-][^\W\d_]+)*", re.UNICODE)
_CAPS_RE = re.compile(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇÜ]{3,}\b")
_OPENER_SPAN_RE = re.compile(
    r'<span[^>]*class="[^"]*(?:CO|dropcap)[^"]*"[^>]*>(.*?)</span>',
    re.DOTALL | re.IGNORECASE,
)
_CAPS_EN = {
    "THE", "AND", "OF", "TO", "IN", "THAT", "HE", "SHE", "IT", "WAS", "WERE",
    "WITH", "FOR", "ON", "AT", "BUT", "HIS", "HER", "THEY", "HAD", "YOU", "NOT",
    "THIS", "FROM", "HAVE", "BY", "BE", "WHICH", "OR", "AN",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _words(text: str) -> List[str]:
    return _WORD_RE.findall(text or "")


def _xhtml_names(archive: zipfile.ZipFile) -> List[str]:
    return sorted(
        name
        for name in archive.namelist()
        if name.lower().endswith((".xhtml", ".html", ".htm"))
        and not name.startswith("META-INF/")
    )


def _text_from_html(raw: str) -> str:
    """Visible text with inline tags joined, never separated by a space."""
    raw = _SCRIPT_STYLE_RE.sub(" ", raw or "")
    raw = _BLOCK_TAG_RE.sub("\n", raw)
    raw = _ANY_TAG_RE.sub("", raw)
    text = html.unescape(raw)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def extract_files(epub_path: str | Path) -> Dict[str, Dict[str, Any]]:
    """Return ``{xhtml name: {text, raw, words}}`` for every document."""
    path = Path(epub_path)
    files: Dict[str, Dict[str, Any]] = {}
    with zipfile.ZipFile(path) as archive:
        for name in _xhtml_names(archive):
            raw = archive.read(name).decode("utf-8", errors="replace")
            text = _text_from_html(raw)
            files[name] = {
                "name": name,
                "text": text,
                "raw": raw,
                "words": len(_words(text)),
            }
    return files


def _term_view(term: Any) -> Dict[str, Any]:
    """Normalize a glossary term object or dict to the fields this module uses."""
    if isinstance(term, dict):
        source = str(term.get("source") or "")
        target = str(term.get("target") or "")
        forbidden = list(term.get("forbidden") or [])
        raw_aliases = term.get("aliases") or []
        if isinstance(raw_aliases, str):
            raw_aliases = raw_aliases.split("|")
        aliases = [str(alias).strip() for alias in raw_aliases if str(alias).strip()]
        alias_targets = dict(term.get("alias_targets") or {})
        accepted_targets = dict(term.get("accepted_targets") or {})
    else:
        source = str(getattr(term, "source", "") or "")
        target = str(getattr(term, "target", "") or "")
        forbidden = list(getattr(term, "forbidden", []) or [])
        aliases = [str(alias) for alias in (getattr(term, "aliases", []) or [])]
        alias_targets = dict(getattr(term, "alias_targets", {}) or {})
        accepted_targets = dict(getattr(term, "accepted_targets", {}) or {})
    forms = [part.strip() for part in source.split("|") if part.strip()]
    if not forms:
        return {}
    if isinstance(term, dict):
        confidence = str(term.get("confidence") or "")
    else:
        confidence = str(getattr(term, "confidence", "") or "")
    return {
        "source": forms[0],
        "forms": forms,
        "aliases": aliases,
        "target": target,
        "alias_targets": alias_targets,
        "accepted_targets": {str(k): [str(v) for v in vs] for k, vs in accepted_targets.items()},
        "forbidden": [str(item) for item in forbidden if item],
        "confidence": confidence,
    }


def _accepted_variant(view: Dict[str, Any], text: str) -> bool:
    """A derived form listed for this target, e.g. "legionários" for "Legião"."""
    variants = (view.get("accepted_targets") or {}).get(view["target"], [])
    text_cf = text.casefold()
    return any(variant.casefold() in text_cf for variant in variants)


def _form_present(form: str, text: str, text_cf: str) -> bool:
    """Substring for multi-word forms, whole word for single words of any length.

    A substring test made ``Cat`` match ``Catch`` and, for longer names, ``Raine``
    match ``drained`` or ``Scholiast`` match ``scholiasts``. Each phantom match made
    a file count as a glossary pair the translation never had to render.
    """
    if " " in form:
        return form.casefold() in text_cf
    return re.search(rf"\b{re.escape(form)}\b", text, re.IGNORECASE) is not None


def _pattern_hits(text: str, patterns: Sequence[str]) -> List[Dict[str, Any]]:
    hits = []
    for pattern in patterns:
        matches = re.findall(pattern, text or "", flags=re.IGNORECASE)
        if matches:
            hits.append({"pattern": pattern, "count": len(matches)})
    return hits


def _pt_pt_hits(text: str) -> List[Dict[str, Any]]:
    return _pattern_hits(text, PT_PT_PATTERNS)


def _pt_pt_blocking_hits(text: str) -> List[Dict[str, Any]]:
    return _pattern_hits(text, PT_PT_BLOCKING_PATTERNS)


def _top(items: Sequence[Dict[str, Any]], key: str, limit: int = 10) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda item: item.get(key) or 0, reverse=True)[:limit]


def _forbidden_occurrences(text: str, forbidden: str, source: str = "") -> int:
    """Count hits of one forbidden form.

    A forbidden form that starts with a capital and is not the English source term is a
    proper-noun rendering (for example Cantaria). A lowercase occurrence of the same letters
    is an ordinary word ('would sing') and is not counted. The English source term (Chantry)
    is always matched case-insensitively, so a lowercase English leak still counts.
    """
    matches = re.findall(rf"\b{re.escape(forbidden)}\b", text, flags=re.IGNORECASE)
    is_english_source = forbidden.lower() == source.lower()
    if forbidden[:1].isupper() and not is_english_source:
        matches = [match for match in matches if match[:1].isupper()]
    return len(matches)


def scan_book(
    source_epub: str | Path,
    target_epub: str | Path,
    terms: Sequence[Any],
    *,
    thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Scan every target XHTML file and return the per-file report and gate."""
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    source_files = extract_files(source_epub)
    target_files = extract_files(target_epub)
    views = [view for view in (_term_view(term) for term in terms) if view]

    normal_counts: Counter = Counter()
    for content in target_files.values():
        for word in _words(content["text"]):
            if not word.isupper():
                normal_counts[word.casefold()] += 1

    target_map: Dict[str, str] = {}
    for view in views:
        target = view["target"].strip()
        if target and " " not in target and len(target) >= 4 and target[0].isupper():
            target_map[target.casefold()] = target
    term_forms = {
        form.casefold()
        for view in views
        for form in view["forms"] + view["aliases"]
        if form
    }

    caps_source_map: Dict[str, str] = {}
    for view in views:
        if not view["target"]:
            continue
        for form in view["forms"] + view["aliases"]:
            caps_source_map[form.casefold()] = view["target"]

    files: List[Dict[str, Any]] = []
    forbidden_all: List[Dict[str, Any]] = []
    glossary_missing: List[Dict[str, Any]] = []
    pt_offenders: List[Dict[str, Any]] = []
    leakage_offenders: List[Dict[str, Any]] = []
    repetition_offenders: List[Dict[str, Any]] = []
    length_offenders: List[Dict[str, Any]] = []
    dropcap_all: List[Dict[str, Any]] = []
    caps_all: List[Dict[str, Any]] = []
    truncated_all: List[Dict[str, Any]] = []

    total_words = 0
    total_pt = 0
    total_blocking = 0
    total_pairs = 0
    total_hits = 0
    blocking: List[str] = []
    warnings: List[str] = []

    for name, content in target_files.items():
        text = content["text"]
        words = content["words"]
        total_words += words
        flags: List[str] = []
        file_warnings: List[str] = []

        forbidden_hits = []
        for view in views:
            for forbidden in view["forbidden"]:
                count = _forbidden_occurrences(text, forbidden, view["source"])
                if count:
                    hit = {
                        "file": name,
                        "source": view["source"],
                        "forbidden": forbidden,
                        "count": count,
                    }
                    forbidden_hits.append(hit)
                    forbidden_all.append(hit)

        source_content = source_files.get(name)
        glossary = {"eligible": 0, "hits": 0, "coverage": None, "missing": []}
        if source_content is not None:
            source_cf = source_content["text"].casefold()
            for view in views:
                if not view["target"]:
                    continue
                if not any(
                    _form_present(form, source_content["text"], source_cf)
                    for form in view["forms"] + view["aliases"]
                    if form
                ):
                    continue
                glossary["eligible"] += 1
                if glossary_target_present(view["target"], text) or _accepted_variant(view, text):
                    glossary["hits"] += 1
                else:
                    missing = {
                        "file": name,
                        "source": view["source"],
                        "target": view["target"],
                        "confidence": view["confidence"],
                    }
                    glossary["missing"].append(missing)
                    glossary_missing.append(missing)
            if glossary["eligible"]:
                glossary["coverage"] = round(
                    glossary["hits"] / glossary["eligible"], 4
                )
            total_pairs += glossary["eligible"]
            total_hits += glossary["hits"]

        pt_hits = _pt_pt_hits(text)
        pt_count = sum(item["count"] for item in pt_hits)
        total_pt += pt_count
        pt_rate = round(pt_count / words * 100_000, 2) if words else 0.0
        blocking_hits = _pt_pt_blocking_hits(text)
        blocking_count = sum(item["count"] for item in blocking_hits)
        total_blocking += blocking_count
        blocking_rate = (
            round(blocking_count / words * 100_000, 2) if words else 0.0
        )
        leak = english_leakage(text)
        repetition = repetition_ratio(text)
        ratio = (
            length_ratio_metric(source_content["text"], text)
            if source_content is not None
            else None
        )

        dropcap = [
            issue.to_dict()
            for issue in _dropcap_html_issues(content["raw"], name)
        ]
        for issue in dropcap:
            issue["file"] = name
            dropcap_all.append(issue)

        caps = _CAPS_RE.findall(text)
        caps_foreign = sorted({token for token in caps if token in _CAPS_EN})
        untranslated = sorted(
            {
                token
                for token in caps
                if token.casefold() in caps_source_map
                and caps_source_map[token.casefold()].casefold() != token.casefold()
            }
        )
        for token in caps_foreign:
            caps_all.append({"file": name, "token": token, "kind": "english"})
        for token in untranslated:
            caps_all.append({"file": name, "token": token, "kind": "untranslated"})

        truncated: List[Dict[str, Any]] = []
        seen_truncated = set()
        for match in _OPENER_SPAN_RE.finditer(content["raw"]):
            inner = html.unescape(_ANY_TAG_RE.sub(" ", match.group(1)))
            for token in _words(inner):
                low = token.casefold()
                if len(low) < 4 or low in target_map or low in term_forms:
                    continue
                if normal_counts.get(low, 0):
                    continue
                for target_low, target in target_map.items():
                    if target_low.startswith(low) and len(target_low) - len(low) >= 2:
                        key = (token, target_low)
                        if key not in seen_truncated:
                            seen_truncated.add(key)
                            hit = {"file": name, "token": token, "expected": target}
                            truncated.append(hit)
                            truncated_all.append(hit)
                        break

        if forbidden_hits:
            flags.append(f"{len(forbidden_hits)} forbidden rendering(s)")
        if (
            glossary["coverage"] is not None
            and glossary["eligible"] >= limits["glossary_file_min_pairs"]
            and glossary["coverage"] < limits["glossary_file_floor"]
        ):
            flags.append(
                f"glossary coverage {glossary['coverage']} < "
                f"{limits['glossary_file_floor']}"
            )
        elif (
            glossary["coverage"] is not None
            and glossary["eligible"] >= limits["glossary_file_min_pairs"]
            and glossary["coverage"] < limits["glossary_coverage"]
        ):
            file_warnings.append(f"glossary coverage {glossary['coverage']}")
        if (
            words >= limits["pt_pt_file_min_words"]
            and blocking_rate > limits["pt_pt_file_per_100k"]
        ):
            flags.append(
                f"pt-PT cluster {blocking_rate} per 100k > "
                f"{limits['pt_pt_file_per_100k']}"
            )
        elif words >= limits["pt_pt_file_min_words"] and blocking_rate > limits["pt_pt_per_100k"]:
            file_warnings.append(f"pt-PT {blocking_rate} per 100k")
        if (
            words >= limits["leakage_file_min_words"]
            and leak is not None
            and leak > limits["leakage_file"]
        ):
            flags.append(
                f"English leakage {leak} > {limits['leakage_file']}"
            )
        elif words >= limits["leakage_file_min_words"] and leak is not None and leak > limits["leakage"]:
            file_warnings.append(f"English leakage {leak}")
        if (
            words >= limits["repetition_file_min_words"]
            and repetition is not None
            and repetition > limits["repetition_file"]
        ):
            flags.append(
                f"repetition {repetition} > {limits['repetition_file']}"
            )
        elif words >= limits["repetition_file_min_words"] and repetition is not None and repetition > limits["repetition"]:
            file_warnings.append(f"repetition {repetition}")
        if (
            ratio is not None
            and source_content is not None
            and source_content["words"] >= limits["length_file_min_source_words"]
            and not limits["length_min"] <= ratio <= limits["length_max"]
        ):
            flags.append(
                f"length ratio {ratio} outside "
                f"{limits['length_min']}-{limits['length_max']}"
            )
        if dropcap:
            flags.append(f"{len(dropcap)} dropcap issue(s)")
        if caps_foreign:
            flags.append(
                "all-caps English token(s): " + ", ".join(caps_foreign)
            )
        if untranslated:
            flags.append(
                "untranslated all-caps term(s): " + ", ".join(untranslated)
            )
        if truncated:
            flags.append(
                "truncated term(s): "
                + ", ".join(f"{hit['token']} -> {hit['expected']}" for hit in truncated)
            )

        pt_offenders.append(
            {
                "file": name,
                "count": pt_count,
                "per_100k": pt_rate,
                "blocking": blocking_count,
                "blocking_per_100k": blocking_rate,
                "patterns": pt_hits,
            }
        )
        leakage_offenders.append({"file": name, "ratio": leak, "words": words})
        repetition_offenders.append(
            {"file": name, "ratio": repetition, "words": words}
        )
        if ratio is not None:
            length_offenders.append(
                {
                    "file": name,
                    "ratio": ratio,
                    "source_words": source_content["words"] if source_content else 0,
                }
            )

        blocking.extend(f"{name}: {flag}" for flag in flags)
        warnings.extend(f"{name}: {warning}" for warning in file_warnings)

        files.append(
            {
                "name": name,
                "words": words,
                "source_words": source_content["words"] if source_content else None,
                "paired": source_content is not None,
                "forbidden": forbidden_hits,
                "glossary": glossary,
                "pt_pt": {
                    "count": pt_count,
                    "per_100k": pt_rate,
                    "blocking": blocking_count,
                    "blocking_per_100k": blocking_rate,
                    "patterns": pt_hits,
                    "blocking_patterns": blocking_hits,
                },
                "english_leakage": leak,
                "repetition_ratio": repetition,
                "length_ratio": ratio,
                "dropcap": dropcap,
                "caps": {
                    "count": len(caps),
                    "english": caps_foreign,
                    "untranslated": untranslated,
                },
                "truncated": truncated,
                "flags": flags,
                "warnings": file_warnings,
            }
        )

    missing_targets = [
        {"file": name, "words": content["words"]}
        for name, content in source_files.items()
        if name not in target_files
        and content["words"] >= limits["missing_target_min_words"]
    ]

    coverage = round(total_hits / total_pairs, 4) if total_pairs else 1.0
    pt_rate_total = (
        round(total_pt / total_words * 100_000, 2) if total_words else 0.0
    )
    blocking_rate_total = (
        round(total_blocking / total_words * 100_000, 2) if total_words else 0.0
    )
    global_leakage = english_leakage(
        "\n\n".join(content["text"] for content in target_files.values())
    )
    global_repetition = repetition_ratio(
        "\n\n".join(content["text"] for content in target_files.values())
    )
    global_ratio = None
    source_words_total = sum(content["words"] for content in source_files.values())
    if source_words_total:
        global_ratio = round(total_words / source_words_total, 4)

    reasons: List[str] = []
    if forbidden_all:
        reasons.append(
            f"forbidden: {len(forbidden_all)} hit(s) in "
            f"{len({hit['file'] for hit in forbidden_all})} file(s)"
        )
    if coverage < limits["glossary_coverage"]:
        reasons.append(
            f"glossary coverage {coverage} < {limits['glossary_coverage']} "
            "(file pairs)"
        )
    low_files = [
        item
        for item in files
        if item["glossary"]["coverage"] is not None
        and item["glossary"]["eligible"] >= limits["glossary_file_min_pairs"]
        and item["glossary"]["coverage"] < limits["glossary_file_floor"]
    ]
    if low_files:
        reasons.append(
            f"glossary coverage < {limits['glossary_file_floor']} in "
            f"{len(low_files)} file(s)"
        )
    if blocking_rate_total > limits["pt_pt_per_100k"]:
        reasons.append(
            f"pt-PT markers {blocking_rate_total} per 100k > "
            f"{limits['pt_pt_per_100k']}"
        )
    pt_clusters = [
        item
        for item in files
        if item["words"] >= limits["pt_pt_file_min_words"]
        and item["pt_pt"]["blocking_per_100k"] > limits["pt_pt_file_per_100k"]
    ]
    if pt_clusters:
        reasons.append(
            f"pt-PT cluster > {limits['pt_pt_file_per_100k']} per 100k in "
            f"{len(pt_clusters)} file(s)"
        )
    if global_leakage > limits["leakage"]:
        reasons.append(
            f"English leakage {global_leakage} > {limits['leakage']}"
        )
    leak_files = [
        item
        for item in files
        if item["words"] >= limits["leakage_file_min_words"]
        and item["english_leakage"] > limits["leakage_file"]
    ]
    if leak_files:
        reasons.append(
            f"English leakage > {limits['leakage_file']} in "
            f"{len(leak_files)} file(s)"
        )
    if global_repetition > limits["repetition"]:
        reasons.append(
            f"repetition {global_repetition} > {limits['repetition']}"
        )
    repetition_files = [
        item
        for item in files
        if item["words"] >= limits["repetition_file_min_words"]
        and item["repetition_ratio"] > limits["repetition_file"]
    ]
    if repetition_files:
        reasons.append(
            f"repetition > {limits['repetition_file']} in "
            f"{len(repetition_files)} file(s)"
        )
    if global_ratio is not None and not limits["length_min"] <= global_ratio <= limits["length_max"]:
        reasons.append(
            f"length ratio {global_ratio} outside "
            f"{limits['length_min']}-{limits['length_max']}"
        )
    length_files = [
        item
        for item in files
        if item["length_ratio"] is not None
        and item["source_words"] is not None
        and item["source_words"] >= limits["length_file_min_source_words"]
        and not limits["length_min"] <= item["length_ratio"] <= limits["length_max"]
    ]
    if length_files:
        reasons.append(
            f"length ratio outside {limits['length_min']}-{limits['length_max']} "
            f"in {len(length_files)} file(s)"
        )
    if dropcap_all:
        reasons.append(f"dropcap integrity: {len(dropcap_all)} issue(s)")
    untranslated_caps = [item for item in caps_all if item["kind"] == "untranslated"]
    if untranslated_caps:
        reasons.append(
            "untranslated all-caps glossary term(s): "
            + ", ".join(sorted({item["token"] for item in untranslated_caps}))
        )
    caps_foreign_all = [item for item in caps_all if item["kind"] == "english"]
    if caps_foreign_all:
        reasons.append(
            "all-caps English token(s): "
            + ", ".join(sorted({item["token"] for item in caps_foreign_all}))
        )
    if truncated_all:
        reasons.append(
            "truncated term(s): "
            + ", ".join(
                sorted(
                    {f"{hit['token']} -> {hit['expected']}" for hit in truncated_all}
                )
            )
        )
    if missing_targets:
        reasons.append(
            f"{len(missing_targets)} source file(s) without a target counterpart"
        )

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "source": str(source_epub),
        "target": str(target_epub),
        "thresholds": limits,
        "totals": {
            "files": len(target_files),
            "files_with_source": sum(1 for item in files if item["paired"]),
            "words": total_words,
            "forbidden_hits": len(forbidden_all),
            "glossary_pairs": total_pairs,
            "glossary_hits": total_hits,
            "glossary_coverage": coverage,
            "pt_pt": total_pt,
            "pt_pt_per_100k": pt_rate_total,
            "pt_pt_blocking": total_blocking,
            "pt_pt_blocking_per_100k": blocking_rate_total,
            "english_leakage": global_leakage,
            "repetition_ratio": global_repetition,
            "length_ratio": global_ratio,
            "dropcap_issues": len(dropcap_all),
            "caps_hits": len(caps_all),
            "truncated_terms": len(truncated_all),
            "missing_targets": len(missing_targets),
        },
        "gate": {
            "passed": not reasons,
            "reasons": reasons,
            "warnings": warnings,
        },
        "offenders": {
            "forbidden": _top(forbidden_all, "count"),
            "glossary_missing": sorted(
                glossary_missing,
                key=lambda item: (
                    item.get("confidence") != "confirmed",
                    item["file"],
                    item["source"],
                ),
            )[:10],
            "pt_pt": _top(
                [
                    item
                    for item in pt_offenders
                    if item["count"] or item["blocking"]
                ],
                "blocking_per_100k",
            ),
            "english_leakage": _top(
                [
                    item
                    for item in leakage_offenders
                    if item["words"] >= limits["leakage_file_min_words"]
                ],
                "ratio",
            ),
            "repetition": _top(
                [
                    item
                    for item in repetition_offenders
                    if item["words"] >= limits["repetition_file_min_words"]
                ],
                "ratio",
            ),
            "length_ratio": sorted(
                [
                    item
                    for item in length_offenders
                    if item["source_words"] >= limits["length_file_min_source_words"]
                    and not limits["length_min"] <= item["ratio"] <= limits["length_max"]
                ],
                key=lambda item: abs(item["ratio"] - 1.0),
                reverse=True,
            )[:10],
            "dropcap": dropcap_all[:10],
            "caps": caps_all[:10],
            "truncated": truncated_all[:10],
            "missing_targets": missing_targets[:10],
        },
        "files": files,
    }
