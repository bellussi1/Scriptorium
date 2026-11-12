"""Targeted repair of hard quality failures in a finished literary EPUB.

Two failures are repaired, both found on the target text alone:

- a forbidden glossary form (for example ``animalcule`` where the glossary says a
  different word), and
- a pt-PT form that the audit counts as blocking (``estamos a``, ``contacto``...).

A paragraph is sent to the model only when one of these is present. The model
gets the paragraph and the exact instructions, and its reply is accepted only if
the failure is gone and the reply keeps the paragraph's numbers, placeholders,
language and length. Anything else keeps the draft, and the report says why.
Paragraphs with inline markup are skipped, as in ``ptbr_revise``.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .per_file_audit import PT_PT_BLOCKING_PATTERNS, _term_view
from .ptbr_revise import _ollama_generate, pt_pt_issues
from .refine_epub import _write_epub, apply_paragraph_replacements, extract_paragraphs
from .validation import _placeholders, detect_language, numeric_tokens

MAX_ATTEMPTS = 2
MIN_SIMILARITY = 0.65  # word-level similarity; below this the model rewrote too much
LENGTH_RANGE = (0.8, 1.2)
MIN_WORDS = 8

SYSTEM_PROMPT = (
    "You repair one paragraph of a Portuguese (Brazil) translation of a novel. "
    "Change only the words named in the instructions. Keep the meaning, names, "
    "numbers, punctuation and every other word exactly as they are. "
    "Return only the repaired paragraph, with no commentary."
)


@dataclass(frozen=True)
class ForbiddenRule:
    source: str
    target: str
    form: str


@dataclass(frozen=True)
class Failure:
    code: str  # "forbidden" or "pt_pt_block"
    instruction: str
    matches: Tuple[str, ...] = ()  # the flagged text, which the repair may change


def rules_from_terms(terms: Sequence[Any]) -> List[ForbiddenRule]:
    rules: List[ForbiddenRule] = []
    for term in terms:
        view = _term_view(term)
        if not view:
            continue
        for form in view["forbidden"]:
            rules.append(ForbiddenRule(view["source"], view["target"], form))
    return rules


def find_failures(text: str, rules: Sequence[ForbiddenRule]) -> List[Failure]:
    failures: List[Failure] = []
    for rule in rules:
        hits = tuple(m.group(0) for m in re.finditer(rf"\b{re.escape(rule.form)}\b", text, flags=re.IGNORECASE))
        if hits:
            failures.append(Failure(
                "forbidden",
                f"Replace '{rule.form}' with '{rule.target}' (glossary term for '{rule.source}').",
                hits,
            ))
    blocking = tuple(
        m.group(0)
        for pattern in PT_PT_BLOCKING_PATTERNS
        for m in re.finditer(pattern, text, flags=re.IGNORECASE)
    )
    if blocking:
        hints = []
        for issue in pt_pt_issues(text)[:4]:
            hint = issue.message
            if issue.suggestions:
                hint += f" Use: {', '.join(issue.suggestions)}."
            hints.append(hint)
        failures.append(Failure(
            "pt_pt_block",
            " ".join(hints) or "Use Brazilian Portuguese forms (você, está, contato, demônio, prêmio).",
            blocking,
        ))
    return failures


def build_messages(draft: str, failures: Sequence[Failure], feedback: str = "") -> List[Dict[str, str]]:
    instructions = "\n".join(f"- {failure.instruction}" for failure in failures)
    note = f"\n\n# PREVIOUS ATTEMPT\n\n{feedback}" if feedback else ""
    user = (
        "# PARAGRAPH\n\n"
        f"{draft.strip()}\n\n"
        "# INSTRUCTIONS\n\n"
        f"{instructions}"
        f"{note}\n\nReturn only the repaired paragraph."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


_WORD = re.compile(r"\w+")
# Words that may disappear without changing the sense: articles, pronouns, short particles.
_FUNCTION_WORDS = frozenset({
    "uma", "uns", "umas", "dos", "das", "nos", "nas", "pelo", "pela", "pelos", "pelas",
    "lhe", "lhes", "meu", "minha", "seu", "sua", "ele", "ela", "eles", "elas", "isso", "isto",
})
MIN_CONTENT_LENGTH = 4  # shorter words are function words in Portuguese
RELATED_RATIO = 0.5  # similarity above which two words are treated as one word family


def _tokens(text: str) -> List[str]:
    return [word.casefold() for word in _WORD.findall(text)]


def _related(a: str, b: str) -> bool:
    return a[:4] == b[:4] or difflib.SequenceMatcher(None, a, b).ratio() >= RELATED_RATIO


def unexpected_removals(draft: str, revised: str, failures: Sequence[Failure]) -> List[str]:
    """Content words the draft had and the reply lost, without a related word replacing them.

    A repair may change the flagged forms and the words of their family (podia ->
    poderia). A verb swapped for another (pagar -> construindo) is a meaning error.
    """
    allowed = {token for failure in failures for match in failure.matches for token in _tokens(match)}
    draft_counts = Counter(_tokens(draft))
    revised_counts = Counter(_tokens(revised))
    removed = [word for word in draft_counts if draft_counts[word] > revised_counts.get(word, 0)]
    added = [word for word in revised_counts if revised_counts[word] > draft_counts.get(word, 0)]
    bad = []
    for word in removed:
        if word in allowed or word in _FUNCTION_WORDS or len(word) < MIN_CONTENT_LENGTH:
            continue
        if any(_related(word, other) for other in added):
            continue
        bad.append(word)
    return sorted(bad)


def guard(draft: str, revised: str, failures: Sequence[Failure]) -> Tuple[bool, List[str]]:
    """Accept a repair only when it is complete and contained."""
    reasons: List[str] = []
    if not revised.strip():
        return False, ["empty revision"]
    draft_words = draft.split()
    revised_words = revised.split()
    similarity = difflib.SequenceMatcher(None, draft_words, revised_words, autojunk=False).ratio()
    if similarity < MIN_SIMILARITY:
        reasons.append(f"too many edits (similarity {similarity:.2f})")
    ratio = len(revised_words) / max(1, len(draft_words))
    if not LENGTH_RANGE[0] <= ratio <= LENGTH_RANGE[1]:
        reasons.append(f"length ratio {ratio:.2f} outside range")
    if numeric_tokens(draft) != numeric_tokens(revised):
        reasons.append("numbers changed")
    if _placeholders(draft) != _placeholders(revised):
        reasons.append("placeholders changed")
    if detect_language(revised) == "en":
        reasons.append("reply is English")
    removed = unexpected_removals(draft, revised, failures)
    if removed:
        reasons.append("unexpected word change: " + ", ".join(removed))
    return not reasons, reasons


def fix_paragraph(
    text: str,
    rules: Sequence[ForbiddenRule],
    generate: Callable[[List[Dict[str, str]]], str],
) -> Dict[str, Any]:
    """Return the repaired paragraph (or the draft) and how the decision was made."""
    failures = find_failures(text, rules)
    codes = sorted({failure.code for failure in failures})
    if not failures:
        return {"accepted": False, "after": text, "codes": codes, "reasons": ["no failure"], "attempts": 0}
    feedback = ""
    reasons: List[str] = ["no attempt"]
    revised = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            revised = (generate(build_messages(text, failures, feedback)) or "").strip()
        except Exception as exc:  # provider failure: keep the draft
            return {"accepted": False, "after": text, "codes": codes, "reasons": [f"error: {exc}"], "attempts": attempt}
        ok, reasons = guard(text, revised, failures)
        if ok:
            remaining = find_failures(revised, rules)
            if not remaining:
                return {"accepted": True, "after": revised, "codes": codes, "reasons": [], "attempts": attempt}
            reasons = [f"failure remains: {failure.code}" for failure in remaining]
        feedback = "The previous attempt was rejected: " + "; ".join(reasons) + ". Change only the named words."
    return {"accepted": False, "after": revised, "codes": codes, "reasons": reasons, "attempts": MAX_ATTEMPTS}


def fix_epub(
    source_path: str,
    output_path: str,
    *,
    rules: Sequence[ForbiddenRule],
    generate: Callable[[List[Dict[str, str]]], str],
    limit: int = 0,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Repair flagged paragraphs of ``source_path`` and write ``output_path``."""
    report: Dict[str, Any] = {
        "paragraphs": 0,
        "flagged": 0,
        "skipped_inline_markup": 0,
        "attempted": 0,
        "accepted": 0,
        "rejected": 0,
        "errors": 0,
        "by_code": {},
        "segments": [],
    }
    changed: Dict[str, bytes] = {}
    with zipfile.ZipFile(source_path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith((".xhtml", ".html"))]
        for name in names:
            raw = archive.read(name).decode("utf-8")
            paragraphs = extract_paragraphs(raw)
            replacements: Dict[int, str] = {}
            for paragraph in paragraphs:
                report["paragraphs"] += 1
                if len(re.findall(r"\w+", paragraph.text)) < MIN_WORDS:
                    continue
                failures = find_failures(paragraph.text, rules)
                if not failures:
                    continue
                report["flagged"] += 1
                for failure in failures:
                    report["by_code"][failure.code] = report["by_code"].get(failure.code, 0) + 1
                if paragraph.has_inline_markup:
                    report["skipped_inline_markup"] += 1
                    continue
                if dry_run:
                    continue
                if limit and report["attempted"] >= limit:
                    continue
                result = fix_paragraph(paragraph.text, rules, generate)
                report["attempted"] += 1
                if result["reasons"] and str(result["reasons"][0]).startswith("error:"):
                    report["errors"] += 1
                report["segments"].append({
                    "file": name,
                    "index": paragraph.index,
                    "codes": result["codes"],
                    "accepted": result["accepted"],
                    "reasons": result["reasons"],
                    "before": paragraph.text,
                    "after": result["after"],
                })
                if result["accepted"]:
                    replacements[paragraph.index] = result["after"]
                    report["accepted"] += 1
                else:
                    report["rejected"] += 1
            if replacements:
                changed[name] = apply_paragraph_replacements(raw, paragraphs, replacements).encode("utf-8")
    if not dry_run and changed:
        _write_epub(source_path, output_path, changed)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--epub", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--author", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--book", required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--limit", type=int, default=0, help="model calls to make (0 = all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.out.resolve() == args.epub.resolve():
        raise SystemExit("--out must differ from --epub")

    from .resources import compile_for_book, load_tree

    tree = load_tree(str(Path(__file__).resolve().parents[2] / "literary-resources"))
    compiled = compile_for_book(tree, args.author, args.universe, "", args.book)
    rules = rules_from_terms(compiled.glossary.terms)
    generate = _ollama_generate(args.model, args.endpoint)
    report = fix_epub(
        str(args.epub), str(args.out), rules=rules, generate=generate,
        limit=args.limit, dry_run=args.dry_run,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k != "segments"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
