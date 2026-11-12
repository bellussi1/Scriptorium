"""Convert European Portuguese forms in a finished pt-BR EPUB to Brazilian Portuguese.

Each flagged paragraph (the ``ptbr.pt_*`` rules of :func:`src.literary.ptbr.check_text`)
goes through two steps:

1. Word swaps that cannot break grammar (de facto, contacto, demónio, prémio,
   -ámos, teu/tua, convosco) are applied directly, without the model.
2. Whatever is left (second-person verbs, "tu", "estar a + infinitivo") is sent
   to the local model, with the remaining findings as the instruction.

The English source is not used: the reader repair changes paragraph boundaries,
so the pairing that the refine pass needs no longer holds. The guard compares
each result with the original paragraph and accepts it only when the European
forms are gone and nothing else moved (numbers, names, length, edit size).

Run from the repository root::

    python -m src.literary.ptbr_revise --epub <in.epub> --out <out.epub> --model <model>

The output is a new file; nothing is overwritten in place.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .ptbr import PtBrIssue, check_text
from .reading_repair import _replace_text_nodes
from .refine_epub import Paragraph, _write_epub, apply_paragraph_replacements, extract_paragraphs

PT_PT_PREFIX = "ptbr.pt_"
# One retry with the guard's reasons: a second answer often fixes the leftover form.
MODEL_ATTEMPTS = 2

# Swaps that are safe without the model: the replacement is a whole word that
# reads the same in every person, so no verb has to change.
SAFE_CODES = {
    "ptbr.pt_de_facto",
    "ptbr.pt_contacto",
    "ptbr.pt_demonio",
    "ptbr.pt_premio",
    "ptbr.pt_ammos",
    "ptbr.pt_convosco",
    "ptbr.pt_teu",
    "ptbr.pt_tua",
}

SYSTEM_PROMPT = """You are a copy editor for a Brazilian Portuguese literary translation.
You receive one paragraph and a list of forms that are European Portuguese and must
become Brazilian Portuguese. Change only what the list asks for:
- Second person "tu" becomes "você", and its verb moves to the third person
  (fizeste -> fez, garantirás -> garantirá, és -> é, compreendes -> entende,
  tens -> tem, sabes -> sabe, abençoa-nos -> abençoe-nos). Teu/tua become seu/sua.
- "estar a" + infinitive becomes "estar" + gerund (estamos a construir -> estamos construindo).
Keep every other word, name, number, punctuation mark and dash exactly as it is.
Keep the meaning and the register. Do not add or remove sentences.
Return only the revised paragraph, with no comments."""

# Capitalised words that the conversion itself removes: "Tu" becomes "Você".
_CONVERTED_CAPS = {"Tu", "Teu", "Teus", "Tua", "Tuas", "Convosco"}
_CAPS_RE = re.compile(r"\b[A-ZÀ-Ý][\wÀ-ÿ'’-]+")
_NUMBER_RE = re.compile(r"\d+")
_WORD_RE = re.compile(r"[\wÀ-ÿ]+")
_ARTICLES = ("o", "a", "os", "as", "um", "uma", "uns", "umas")
# Clitics and possessives change with the person: "te" -> "se", "teu" -> "seu".
_PERSON_PAIRS = {("te", "se"), ("teu", "seu"), ("tua", "sua"), ("teus", "seus"), ("tuas", "suas")}


def pt_pt_issues(text: str) -> List[PtBrIssue]:
    """The European-Portuguese findings in one paragraph."""
    return [issue for issue in check_text(text) if issue.code.startswith(PT_PT_PREFIX)]


def safe_fixes(text: str, issues: Sequence[PtBrIssue]) -> str:
    """Apply the word swaps in SAFE_CODES; everything else is left for the model."""
    result = text
    for issue in sorted(issues, key=lambda item: item.start, reverse=True):
        if issue.code in SAFE_CODES and issue.suggestions:
            result = result[: issue.start] + issue.suggestions[0] + result[issue.end :]
    return result


def build_messages(draft: str, issues: Sequence[PtBrIssue], feedback: str = "") -> List[Dict[str, str]]:
    lines = [f'- "{draft[issue.start : issue.end]}": {issue.message}' for issue in issues]
    note = f"\n\n# PREVIOUS ATTEMPT\n\n{feedback}" if feedback else ""
    user = (
        "# PARAGRAPH\n\n"
        f"{draft.strip()}\n\n"
        "# FORMS TO CONVERT\n\n"
        + "\n".join(lines)
        + note
        + "\n\nReturn only the revised paragraph."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _allowed_removals(draft: str, issues: Sequence[PtBrIssue]) -> Counter:
    """Words the revision may drop: each flagged span, and the word that follows it.

    "estamos a construir" -> "estamos construindo" drops "construir", which is the
    word after the flagged "estamos a".
    """
    # Articles may go with a possessive: "as tuas visões" -> "suas visões".
    allowed: Counter = Counter({word: 1 for word in _ARTICLES})
    for issue in issues:
        allowed.update(w.lower() for w in _WORD_RE.findall(draft[issue.start : issue.end]))
        following = re.match(r"\W*([\wÀ-ÿ]+)", draft[issue.end :])
        if following:
            allowed[following.group(1).lower()] += 1
    return allowed


def _same_word_family(word: str, added: Sequence[str]) -> bool:
    """A verb or spelling variant of an added word: 'esperas' ~ 'espera', 'registo' ~ 'registro'."""
    if any((word, other) in _PERSON_PAIRS for other in added):
        return True
    for other in added:
        shared = 0
        for a, b in zip(word, other):
            if a != b:
                break
            shared += 1
        if shared >= max(3, len(word) - 3) and shared >= max(3, len(other) - 3):
            return True
    return False


def _mid_sentence_names(text: str) -> List[str]:
    """Capitalised words that are not at the start of a sentence, so they must survive."""
    names: List[str] = []
    for match in _CAPS_RE.finditer(text):
        before = text[: match.start()].rstrip()
        if not before or before[-1] in ".!?…:;\"“”—–-":
            continue
        if match.group(0) in _CONVERTED_CAPS:
            continue
        names.append(match.group(0))
    return names


def guard(draft: str, revised: str, issues: Sequence[PtBrIssue] = ()) -> Tuple[bool, List[str]]:
    """Accept a revision only when the conversion is complete and contained."""
    reasons: List[str] = []
    if not revised.strip():
        return False, ["empty revision"]
    draft_words = Counter(w.lower() for w in _WORD_RE.findall(draft))
    revised_words = Counter(w.lower() for w in _WORD_RE.findall(revised))
    removed = draft_words - revised_words
    added = list((revised_words - draft_words).keys())
    unexpected = sorted(
        word
        for word in (removed - _allowed_removals(draft, issues)).keys()
        if not _same_word_family(word, added)
    )
    if unexpected:
        reasons.append(f"words changed outside the flagged forms: {unexpected}")
    edit = 1.0 - difflib.SequenceMatcher(None, draft, revised).ratio()
    if edit > 0.35:
        reasons.append(f"edit ratio {edit:.2f} above 0.35")
    length = len(revised) / max(1, len(draft))
    if not 0.80 <= length <= 1.20:
        reasons.append(f"length ratio {length:.2f} outside [0.80, 1.20]")
    if sorted(_NUMBER_RE.findall(draft)) != sorted(_NUMBER_RE.findall(revised)):
        reasons.append("numbers changed")
    missing = sorted(name for name in _mid_sentence_names(draft) if name not in revised)
    if missing:
        reasons.append(f"capitalised words lost: {missing}")
    remaining = pt_pt_issues(revised)
    if remaining:
        reasons.append("still European: " + ", ".join(sorted({issue.code for issue in remaining})))
    return not reasons, reasons


def revise_paragraph(
    text: str,
    generate: Callable[[List[Dict[str, str]]], str],
) -> Dict[str, Any]:
    """Return the revised text for one paragraph and how it was produced."""
    issues = pt_pt_issues(text)
    base = safe_fixes(text, issues)
    remaining = pt_pt_issues(base)
    if not remaining:
        ok, reasons = guard(text, base, issues)
        return {"method": "swap", "accepted": ok, "reasons": reasons, "after": base, "codes": _codes(issues)}
    feedback = ""
    revised, reasons = "", ["no attempt"]
    for _attempt in range(MODEL_ATTEMPTS):
        try:
            revised = (generate(build_messages(base, remaining, feedback)) or "").strip()
        except Exception as exc:  # provider failure: keep the draft
            return {"method": "model", "accepted": False, "reasons": [f"error: {exc}"], "after": "", "codes": _codes(issues)}
        ok, reasons = guard(text, revised, issues)
        if ok:
            return {"method": "model", "accepted": True, "reasons": [], "after": revised, "codes": _codes(issues)}
        feedback = (
            "The previous attempt was rejected: "
            + "; ".join(reasons)
            + ". Change only the listed forms and keep every other word as it is."
        )
    return {"method": "model", "accepted": False, "reasons": reasons, "after": revised, "codes": _codes(issues)}


def _swap_text(text: str) -> str:
    """Safe word swaps inside one text node (used for paragraphs with inline markup)."""
    issues = pt_pt_issues(text)
    return safe_fixes(text, issues) if issues else text


def _codes(issues: Sequence[PtBrIssue]) -> List[str]:
    return sorted({issue.code for issue in issues})


def revise_epub(
    source_path: str,
    output_path: str,
    *,
    generate: Callable[[List[Dict[str, str]]], str],
    limit: int = 0,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Revise flagged paragraphs of ``source_path`` and write ``output_path``."""
    report: Dict[str, Any] = {
        "paragraphs": 0,
        "flagged": 0,
        "skipped_inline_markup": 0,
        "swapped": 0,
        "attempted": 0,
        "accepted": 0,
        "rejected": 0,
        "errors": 0,
        "segments": [],
    }
    changed: Dict[str, bytes] = {}
    with zipfile.ZipFile(source_path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith((".xhtml", ".html"))]
        for name in names:
            raw = archive.read(name).decode("utf-8")
            paragraphs = extract_paragraphs(raw)
            replacements: Dict[int, str] = {}
            for paragraph in paragraphs:
                report["paragraphs"] += 1
                issues = pt_pt_issues(paragraph.text)
                if not issues:
                    continue
                report["flagged"] += 1
                if paragraph.has_inline_markup:
                    report["skipped_inline_markup"] += 1
                    continue
                if dry_run:
                    continue
                needs_model = bool(pt_pt_issues(safe_fixes(paragraph.text, issues)))
                if needs_model and limit and report["attempted"] >= limit:
                    continue
                result = revise_paragraph(paragraph.text, generate)
                entry: Dict[str, Any] = {
                    "file": name,
                    "index": paragraph.index,
                    "before": paragraph.text,
                    "codes": result["codes"],
                    "method": result["method"],
                    "accepted": result["accepted"],
                    "reasons": result["reasons"],
                    "after": result["after"],
                }
                report["segments"].append(entry)
                if result["method"] == "swap":
                    report["swapped"] += 1
                else:
                    report["attempted"] += 1
                if result["method"] == "model" and result["reasons"] and result["reasons"][0].startswith("error:"):
                    report["errors"] += 1
                if result["accepted"]:
                    replacements[paragraph.index] = result["after"]
                    report["accepted"] += 1
                else:
                    report["rejected"] += 1
            # Word swaps also reach paragraphs with inline markup (run-in spans,
            # italics): they only touch text nodes, so the markup stays intact.
            doc = apply_paragraph_replacements(raw, paragraphs, replacements) if replacements else raw
            doc, touched = _replace_text_nodes(doc, _swap_text)
            report["inline_text_nodes_changed"] = report.get("inline_text_nodes_changed", 0) + touched
            if doc != raw:
                changed[name] = doc.encode("utf-8")
    if not dry_run and changed:
        _write_epub(source_path, output_path, changed)
    return report


def _ollama_generate(model: str, endpoint: str) -> Callable[[List[Dict[str, str]]], str]:
    """Chat call with reasoning off: the model otherwise spends the whole budget thinking."""
    import requests

    def generate(messages: List[Dict[str, str]]) -> str:
        response = requests.post(
            endpoint.rstrip("/") + "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {"temperature": 0.0, "num_predict": 800, "num_ctx": 4096},
            },
            timeout=900,
        )
        response.raise_for_status()
        return ((response.json().get("message") or {}).get("content") or "").strip()

    return generate


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--epub", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--limit", type=int, default=0, help="model calls to make (0 = all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.out.resolve() == args.epub.resolve():
        raise SystemExit("--out must differ from --epub")
    generate = _ollama_generate(args.model, args.endpoint)
    report = revise_epub(
        str(args.epub), str(args.out), generate=generate, limit=args.limit, dry_run=args.dry_run
    )
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k != "segments"}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
