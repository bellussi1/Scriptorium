"""Reader-facing repairs for translated EPUBs.

The upstream translator preserves the source paragraph tags but lets chunk
boundaries leak into the text: a sentence can end in one ``<p>`` and continue in
the next, dialogue keeps English quotation marks, and chapter headings can
carry stray dashes or stale titles.  This module repairs the *reading* layer
without retranslating:

* joins body paragraphs that were split mid-sentence;
* converts English dialogue quotes to Brazilian travessões;
* normalises the Sun Eater glossary terms and casing;
* fixes known heading/TOC/nav artefacts;
* adds a conservative reading stylesheet for KOReader.

It is deliberately conservative.  It never rewrites a whole sentence, and the
only book-specific rules live in :data:`SUN_EATER_TERMS` and the small
``reader-repairs.yaml`` (headings) and the ``JOIN_OVERRIDES`` table.
"""
from __future__ import annotations

import html
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from .epub import iter_spine_documents

READER_REPAIRS_PATH = (
    Path(__file__).resolve().parents[2]
    / "literary-resources" / "christopher-ruocchio" / "sun-eater" / "reader-repairs.yaml"
)


@lru_cache(maxsize=1)
def _reader_repairs() -> Dict[str, Any]:
    """Series-level repairs kept as data, not as code."""
    return yaml.safe_load(READER_REPAIRS_PATH.read_text(encoding="utf-8")) or {}

TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
P_RE = re.compile(r"<p\b(?P<attrs>[^>]*)>(?P<inner>.*?)</p\s*>", re.IGNORECASE | re.DOTALL)
CLASS_RE = re.compile(r'class="([^"]*)"', re.IGNORECASE)
BODY_CLASS = "x04-Body-Text"
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# Portuguese function words used only to decide whether a capitalised word is
# the continuation of a noun phrase (``Bassander`` + ``Lin``) or a new sentence.
_FUNCTION_WORDS = set(
    """
    o a os as um uma uns umas de do da dos das em no na nos nas por pelo pela
    pelos pelas para com sem sob sobre entre ate até como que e ou mas se ao
    aos à às seu sua seus suas meu minha meus minhas nosso nossa nossos nossas
    este esta estes estas esse essa esses essas aquele aquela aqueles aquelas
    isto isso aquilo lhe me te nos vos ele ela eles elas nao não ja já ainda
    tambem também so só muito mais menos bem mal entao então agora depois antes
    enquanto embora pois portanto assim talvez quase apenas cada todos todas
    todo toda outro outra outros outras mesmo mesma proprio própria qual quais
    quem cujo cuja aqui ali la lá sempre nunca jamais sim
    """.split()
)


@dataclass
class RepairReport:
    source: str
    output: str
    merged: int = 0
    quote_paragraphs: int = 0
    straight_quote_paragraphs: int = 0
    term_changes: Dict[str, int] = field(default_factory=dict)
    heading_changes: List[str] = field(default_factory=list)
    artefact_changes: Dict[str, int] = field(default_factory=dict)
    documents: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.source,
            "output": self.output,
            "documents": self.documents,
            "merged": self.merged,
            "quote_paragraphs": self.quote_paragraphs,
            "straight_quote_paragraphs": self.straight_quote_paragraphs,
            "term_changes": self.term_changes,
            "heading_changes": self.heading_changes,
            "artefact_changes": self.artefact_changes,
            "warnings": self.warnings,
        }


def strip_tags(value: str) -> str:
    return TAG_RE.sub("", value or "")


def paragraph_text(inner: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(strip_tags(inner))).strip()


def _is_body(attrs: str) -> bool:
    match = CLASS_RE.search(attrs or "")
    if not match:
        return False
    classes = match.group(1).split()
    return any(
        name in classes
        for name in ("x04-Body-Text", "x04-Body-Text-FL", "x03-CO-Body-Text")
    )


def _is_dialogue_body(attrs: str) -> bool:
    match = CLASS_RE.search(attrs or "")
    if not match:
        return False
    classes = match.group(1).split()
    return any(
        name in classes
        for name in ("x04-Body-Text", "x04-Body-Text-FL", "x03-CO-Body-Text")
    )


def _is_scene_break(text: str) -> bool:
    return bool(re.fullmatch(r"[\s*∗·•—–\-_.…]+", text or ""))


def _last_word(text: str) -> str:
    match = re.search(r"([A-Za-zÀ-ÿ]+)\s*$", text or "")
    return match.group(1).casefold() if match else ""


def _capitalise_first_text(inner: str) -> str:
    parts = re.split(r"(<[^>]+>)", inner)
    for index, part in enumerate(parts):
        if part.startswith("<"):
            continue
        stripped = part.lstrip()
        if not stripped:
            continue
        parts[index] = part[: len(part) - len(stripped)] + stripped[0].upper() + stripped[1:]
        break
    return "".join(parts)


def _join_inner(first: str, second: str, mode: str) -> str:
    first = first.rstrip()
    second = second.lstrip()
    if mode == "capitalize":
        second = _capitalise_first_text(second)
    if not first:
        return second
    if not second:
        return first
    if mode == "tight":
        return first + second
    if mode == "period":
        return first + ". " + second
    if first[-1] in "([{“‘" or (first[-1] == "-" and second[0].islower()):
        return first + second
    return first + " " + second


def _merge_mode(previous: str, following: str) -> Optional[str]:
    """Return how two adjacent body paragraphs should be joined, if at all."""
    if not previous or not following:
        return None
    if _is_scene_break(previous) or _is_scene_break(following):
        return None
    if following[0] in "—–":
        return None
    # Deliberate one-word refrains such as "Covarde" / "covarde" / "covarde."
    if (
        len(previous.split()) == 1
        and len(following.split()) <= 2
        and previous.casefold().strip(".,!?;:") == following.casefold().strip(".,!?;:")
    ):
        return None

    # A closing quote at the start of a paragraph belongs to the previous one.
    if following[0] in "”’":
        return "tight"
    # Explicit punctuation at the start of the next paragraph belongs to the
    # previous one.
    if following[0] in ".,;:!?…":
        if previous[-1] in ".!?…":
            return None
        return "tight"

    # An ellipsis is a pause, not a sentence end: "daquelas... criaturas"
    if previous.endswith(("...", "…")):
        return "space" if following[0].islower() else None
    if previous[-1] in ".!?":
        return "capitalize" if following[0].islower() else None
    if previous[-1] in "”’":
        return "space" if following[0].islower() else None
    if previous[-1] in ",;":
        return "space"
    if previous[-1] == ":":
        # A colon at the end of a paragraph introduces the next paragraph.
        return None
    if previous[-1] in "—–":
        return "space"
    if previous[-1] in ")]":
        return "space" if following[0].islower() else None
    if previous[-1].isalnum():
        if following[0].islower():
            return "space"
        if following[0].isupper():
            # Keep proper-name continuations together (Bassander + Lin,
            # Kharn + Sagara).  Missing full stops are fixed by JOIN_OVERRIDES.
            return "space"
        return "tight"
    return "space"


def _apply_join_overrides(previous: str, following: str) -> Optional[str]:
    for suffix, prefix in JOIN_OVERRIDES:
        if previous.endswith(suffix) and following.startswith(prefix):
            return "period"
    return None


def merge_split_paragraphs(raw: str) -> Tuple[str, int]:
    """Join adjacent ``x04-Body-Text`` paragraphs split by a chunk boundary."""
    # The upstream writer sometimes leaves an empty self-closing paragraph at
    # a chunk seam.  It is not a real paragraph and confuses the matcher.
    # An empty paragraph that carries an id is an anchor target (a contents link in
    # Calibre books points at it), so it is kept.
    raw = re.sub(r"<p\b(?![^>]*\sid\s*=)[^>]*/>\s*", "", raw or "", flags=re.IGNORECASE)

    def drop_empty(match: re.Match) -> str:
        inner = match.group("inner")
        if paragraph_text(inner):
            return match.group(0)
        if re.search(r"\sid\s*=", match.group("attrs") or ""):
            return match.group(0)
        if 'epub:type="pagebreak"' in inner or "<img" in inner.lower():
            return match.group(0)
        return ""

    raw = P_RE.sub(drop_empty, raw)
    matches = list(P_RE.finditer(raw or ""))
    if not matches:
        return raw, 0
    rendered: List[str] = []
    cursor = 0
    previous: Optional[Dict[str, str]] = None
    merged = 0

    def render(item: Dict[str, str]) -> str:
        return item["open"] + item["inner"] + item["close"]

    for match in matches:
        prefix = raw[cursor : match.start()]
        attrs = match.group("attrs")
        inner = match.group("inner")
        if not _is_body(attrs):
            if previous is not None:
                rendered.append(previous["prefix"] + render(previous))
                previous = None
            rendered.append(prefix + match.group(0))
            cursor = match.end()
            continue
        text = paragraph_text(inner)
        if previous is not None:
            mode = _apply_join_overrides(previous["text"], text) or _merge_mode(previous["text"], text)
            if mode:
                previous["inner"] = _join_inner(previous["inner"], inner, mode)
                previous["text"] = paragraph_text(previous["inner"])
                merged += 1
                cursor = match.end()
                continue
            if previous["text"].endswith(":") and text[:1].islower():
                # Keep the paragraph break but start the new paragraph with a
                # capital, as a colon normally introduces a new sentence.
                inner = _capitalise_first_text(inner)
                text = paragraph_text(inner)
        if previous is not None:
            rendered.append(previous["prefix"] + render(previous))
        previous = {
            "prefix": prefix,
            "open": raw[match.start() : match.end(1)] + ">",
            "inner": inner,
            "close": raw[match.end(2) : match.end()],
            "text": text,
        }
        cursor = match.end()
    if previous is not None:
        rendered.append(previous["prefix"] + render(previous))
    rendered.append(raw[cursor:])
    return "".join(rendered), merged


def _normalise_straight_quotes_in_paragraph(inner: str) -> Tuple[str, bool, bool]:
    """Turn paired ASCII quotes into curly quotes inside one paragraph."""
    if '"' not in inner:
        return inner, False, False
    parts = re.split(r"(<[^>]+>)", inner)
    opened = 0
    changed = False
    odd = False
    for index, part in enumerate(parts):
        if part.startswith("<") or '"' not in part:
            continue
        chars = []
        for char in part:
            if char == '"':
                chars.append("“" if opened % 2 == 0 else "”")
                opened += 1
                changed = True
            else:
                chars.append(char)
        parts[index] = "".join(chars)
    return "".join(parts), changed, bool(opened % 2)


def normalise_straight_quotes(raw: str) -> Tuple[str, int, List[str]]:
    """Normalise ASCII dialogue quotes in body paragraphs."""
    changed = 0
    warnings: List[str] = []
    matches = list(P_RE.finditer(raw or ""))
    if not matches:
        return raw, 0, warnings
    out: List[str] = []
    cursor = 0
    for match in matches:
        attrs, inner = match.group("attrs"), match.group("inner")
        if not _is_body(attrs):
            continue
        fixed, did_change, odd = _normalise_straight_quotes_in_paragraph(inner)
        if odd:
            warnings.append(f"odd number of straight quotes in paragraph: {paragraph_text(inner)[:80]}")
            continue
        if did_change:
            changed += 1
            out.append(raw[cursor : match.start(2)])
            out.append(fixed)
            cursor = match.end(2)
    if not changed:
        return raw, 0, warnings
    out.append(raw[cursor:])
    return "".join(out), changed, warnings


def _segments_with_plain(inner: str) -> Tuple[List[str], str, List[Tuple[int, int]]]:
    parts = re.split(r"(<[^>]+>)", inner)
    plain_chars: List[str] = []
    mapping: List[Tuple[int, int]] = []
    for segment_index, part in enumerate(parts):
        if part.startswith("<"):
            continue
        for char_index, char in enumerate(part):
            plain_chars.append(char)
            mapping.append((segment_index, char_index))
    return parts, "".join(plain_chars), mapping


def _prev_nonspace(plain: str, index: int) -> int:
    cursor = index - 1
    while cursor >= 0 and plain[cursor].isspace():
        cursor -= 1
    return cursor


def _next_nonspace(plain: str, index: int) -> int:
    cursor = index + 1
    while cursor < len(plain) and plain[cursor].isspace():
        cursor += 1
    return cursor


_SPEECH_VERBS = (
    "disse", "perguntou", "respondeu", "gritou", "exclamou", "murmurou",
    "retrucou", "indagou", "falou", "acrescentou", "continuou", "começou",
    "concluiu", "pediu", "ordenou", "sussurrou", "berrou", "chamou",
    "repetiu", "explicou", "anunciou", "declarou", "confessou", "admitiu",
    "sugeriu", "observou", "comentou", "protestou", "insistiu", "resmungou",
    "rosnou", "gaguejou", "implorou", "avisou", "prometeu", "jurou",
    "acrescentei", "respondi", "perguntei", "gritei", "murmurei", "falei",
    "retruquei", "indaguei", "sugeri", "expliquei", "confessei", "admiti",
    "lembrei", "pensei", "comecei", "continuei", "prossegui", "insisti",
    "declarei", "anunciei", "pedi", "ordenei", "sussurrei", "berrei",
    "chamei", "repeti", "observei", "comentei", "protestei", "resmunguei",
    "rosnei", "gaguejei", "implorei", "avisei", "prometi", "jurei",
)


def _quote_pairs(plain: str) -> List[Tuple[int, int]]:
    pairs: List[Tuple[int, int]] = []
    opened: Optional[int] = None
    for index, char in enumerate(plain):
        if char == "“":
            opened = index
        elif char == "”" and opened is not None:
            pairs.append((opened, index))
            opened = None
    return pairs


def _is_dialogue_pair(plain: str, opening: int, closing: int) -> bool:
    content = plain[opening + 1 : closing].strip()
    if not content:
        return False
    if len(content.split()) > 3:
        return True
    if content.rstrip().endswith((".", "!", "?", "…", "—", "–")):
        return True
    if "—" in content or "–" in content:
        return True
    before = plain[max(0, opening - 70) : opening].casefold()
    after = plain[closing + 1 : closing + 70].casefold()
    if any(verb in before for verb in _SPEECH_VERBS):
        return True
    if any(verb in after for verb in _SPEECH_VERBS):
        return True
    if ":" in plain[max(0, opening - 20) : opening]:
        return True
    return False


def convert_dialogue_quotes(raw: str) -> Tuple[str, int]:
    """Convert English curly dialogue quotes to Brazilian travessões.

    Paragraphs that open with a quote are dialogue and convert completely.
    Inline quotes are converted only when the quoted material is a sentence or
    follows a speech verb; short quoted terms (``a “verdade” do Império``) keep
    their quotation marks.
    """
    matches = list(P_RE.finditer(raw or ""))
    if not matches:
        return raw, 0
    out: List[str] = []
    cursor = 0
    converted = 0
    for match in matches:
        attrs, inner = match.group("attrs"), match.group("inner")
        if not _is_dialogue_body(attrs):
            continue
        text = paragraph_text(inner)
        if "“" not in text and "”" not in text:
            continue
        parts, plain, _mapping = _segments_with_plain(inner)
        pairs = _quote_pairs(plain)
        starts_with_quote = plain.lstrip().startswith("“")
        converted_opens: set[int] = set()
        converted_closes: set[int] = set()
        for opening, closing in pairs:
            if starts_with_quote or _is_dialogue_pair(plain, opening, closing):
                converted_opens.add(opening)
                converted_closes.add(closing)
        # A multi-paragraph quote may have an opening mark without a nearby
        # closing mark; convert it when it opens the paragraph.
        if starts_with_quote:
            first = len(plain) - len(plain.lstrip())
            if plain[first] == "“" and first not in converted_opens:
                converted_opens.add(first)
        if not converted_opens and not converted_closes:
            continue

        replacements: Dict[int, str] = {}
        deletions: set[int] = set()

        for index in sorted(converted_opens):
            prev_index = _prev_nonspace(plain, index)
            if prev_index < 0:
                replacements[index] = "— "
                continue
            prev_char = plain[prev_index]
            glued = index > 0 and not plain[index - 1].isspace()
            if prev_char in ".?!…":
                replacements[index] = " — " if glued else "— "
            elif prev_char in ",;":
                replacements[index] = " — " if glued else "— "
                deletions.add(prev_index)
            elif prev_char == ":":
                replacements[index] = "— "
            elif prev_char in "([{":
                replacements[index] = "— "
            else:
                replacements[index] = " — "

        for index in sorted(converted_closes):
            next_index = _next_nonspace(plain, index)
            if next_index >= len(plain):
                replacements[index] = ""
                continue
            next_char = plain[next_index]
            if next_char == "“":
                replacements[index] = ""
            elif next_char in ",;":
                replacements[index] = " —"
                deletions.add(next_index)
            elif next_char == ":":
                replacements[index] = ""
            elif next_char in ".?!…":
                after = _next_nonspace(plain, next_index)
                if after < len(plain) and plain[after].islower():
                    replacements[index] = " —"
                    deletions.add(next_index)
                else:
                    replacements[index] = ""
            elif next_char.islower():
                replacements[index] = " —"
            elif next_char.isupper():
                replacements[index] = ""
            elif next_char in ")]}":
                replacements[index] = ""
            else:
                replacements[index] = ""

        rebuilt: List[str] = []
        plain_index = 0
        for part in parts:
            if part.startswith("<"):
                rebuilt.append(part)
                continue
            buffer: List[str] = []
            for char in part:
                if plain_index in deletions:
                    plain_index += 1
                    continue
                buffer.append(replacements.get(plain_index, char))
                plain_index += 1
            rebuilt.append("".join(buffer))
        result = "".join(rebuilt)
        result = re.sub(r"\s+", " ", result)
        result = re.sub(r"\s+([,.;:!?…])", r"\1", result)
        result = re.sub(r",\s*—", " —", result)
        result = re.sub(r"—\s*—", "—", result)
        result = re.sub(r"([“])\s+", r"\1", result)
        result = re.sub(r"\s+([”’])", r"\1", result)
        result = re.sub(r"\s{2,}", " ", result).strip()
        out.append(raw[cursor : match.start(2)])
        out.append(result)
        cursor = match.end(2)
        converted += 1
    if not converted:
        return raw, 0
    out.append(raw[cursor:])
    return "".join(out), converted


def _tag_name(tag: str) -> str:
    match = re.match(r"</?\s*([A-Za-z0-9:_-]+)", tag or "")
    return match.group(1).casefold() if match else ""


def split_dialogue_paragraphs(raw: str) -> Tuple[str, int]:
    """Split a long paragraph at clear new-speaker travessão boundaries.

    Chunk-boundary merging can leave several speakers in one very long
    paragraph.  A new speaker starts with ``— `` followed by a capital after
    sentence punctuation; narration tags (``— disse ele``) stay in place.

    The splitter tracks inline tags.  It only cuts at a travessão outside any
    open inline element, so an italic span can never cross the new ``<p>``
    boundary (which would make the XHTML invalid).
    """
    matches = list(P_RE.finditer(raw or ""))
    if not matches:
        return raw, 0
    out: List[str] = []
    cursor = 0
    splits = 0
    for match in matches:
        attrs, inner = match.group("attrs"), match.group("inner")
        if not _is_dialogue_body(attrs):
            continue
        text = paragraph_text(inner)
        if text.count("—") < 4:
            continue
        tokens = re.split(r"(<[^>]+>)", inner)
        stack: List[str] = []
        chars: List[Tuple[str, int, int, int]] = []
        for token_index, token in enumerate(tokens):
            if token.startswith("<"):
                if token.startswith("</"):
                    if stack:
                        stack.pop()
                elif not token.endswith("/>"):
                    stack.append(_tag_name(token))
                continue
            for char_index, char in enumerate(token):
                chars.append((char, token_index, char_index, len(stack)))

        candidates: set[Tuple[int, int]] = set()
        for index, (char, token_index, char_index, depth) in enumerate(chars):
            if char != "—" or depth:
                continue
            before = index - 1
            while before >= 0 and chars[before][0].isspace():
                before -= 1
            after = index + 1
            while after < len(chars) and chars[after][0].isspace():
                after += 1
            if before < 0 or after >= len(chars):
                continue
            if chars[before][0] in ".!?…”" and (
                chars[after][0].isupper() or chars[after][0] == "“"
            ):
                candidates.add((token_index, char_index))
        if not candidates:
            continue

        opening = raw[match.start() : match.end(1)] + ">"
        rebuilt: List[str] = []
        for token_index, token in enumerate(tokens):
            if token.startswith("<"):
                rebuilt.append(token)
                continue
            positions = sorted(
                char_index
                for candidate_token, char_index in candidates
                if candidate_token == token_index
            )
            if not positions:
                rebuilt.append(token)
                continue
            last = 0
            for char_index in positions:
                rebuilt.append(token[last:char_index].rstrip())
                rebuilt.append("</p>" + opening + token[char_index])
                last = char_index + 1
            rebuilt.append(token[last:])
        replacement = "".join(rebuilt)
        out.append(raw[cursor : match.start(2)])
        out.append(replacement)
        cursor = match.end(2)
        splits += len(candidates)
    if not splits:
        return raw, 0
    out.append(raw[cursor:])
    return "".join(out), splits


def _map_text_nodes(inner: str, transform) -> str:
    parts = re.split(r"(<[^>]+>)", inner)
    for index, part in enumerate(parts):
        if not part.startswith("<"):
            parts[index] = transform(part)
    return "".join(parts)


def _replace_text_nodes(raw: str, transform) -> Tuple[str, int]:
    """Apply ``transform`` to text nodes of body paragraphs and table cells."""
    changed = 0
    matches = list(P_RE.finditer(raw or ""))
    if not matches:
        return raw, 0
    out: List[str] = []
    cursor = 0
    for match in matches:
        attrs, inner = match.group("attrs"), match.group("inner")
        # Apply glossary and artefact fixes to every prose paragraph, including
        # scene-break first paragraphs and the Dramatis Personae lists.  Verse
        # is left alone because its punctuation and casing are deliberate.
        if "x06-Verse" in attrs:
            continue
        fixed = _map_text_nodes(inner, transform)
        if fixed != inner:
            changed += 1
            out.append(raw[cursor : match.start(2)])
            out.append(fixed)
            cursor = match.end(2)
    if not changed:
        return raw, 0
    out.append(raw[cursor:])
    return "".join(out), changed


def _replace_terms_in_text(text: str, counts: Dict[str, int]) -> str:
    # Targeted phrases first: generic replacements would destroy the context
    # needed to resolve them.
    for old, new, label in _reader_repairs()["reader_phrases"]:
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            counts[label] = counts.get(label, 0) + count

    for old, new in _reader_repairs()["reader_terms"]:
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            counts[f"{old}→{new}"] = counts.get(f"{old}→{new}", 0) + count
    # Cielcin / Escoliasta are common nouns in the official Brazilian edition.
    for old, new in _reader_repairs()["reader_casing"]:
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            counts[f"{old}→{new}"] = counts.get(f"{old}→{new}", 0) + count
    # Restore the vocative capital: "— Cielcin, este é Bassander Lin."
    text = re.sub(r"(—\s*)cielcin([,!?])", r"\1Cielcin\2", text)
    text = re.sub(r"(—\s*)escoliasta([,!?])", r"\1Escoliasta\2", text)
    return text


def apply_sun_eater_terms(raw: str, counts: Dict[str, int]) -> Tuple[str, int]:
    return _replace_text_nodes(raw, lambda value: _replace_terms_in_text(value, counts))


def _replace_case_preserving(text: str, old: str, new: str) -> str:
    """Replace a term and keep the original case (CHANTRY -> CHANTRIA)."""

    def replace(match: re.Match) -> str:
        word = match.group(0)
        if word.isupper():
            return new.upper()
        if word.islower():
            return new.lower()
        return new

    return re.sub(rf"\b{re.escape(old)}\b", replace, text, flags=re.IGNORECASE)


COPYRIGHT_PAIRS = [
    ("FEITO EM EUA", "FEITO NOS EUA"),
    ("IMPRESSO EM EUA", "IMPRESSO NOS EUA"),
]


def _book_text_fixes(queue_title: str) -> Dict[str, Any]:
    """Book-specific text fixes, keyed by the queue title in reader-repairs.yaml."""
    return _reader_repairs().get("book_text_fixes", {}).get(queue_title, {}) or {}


def global_text_fixes(raw: str, book_fixes: Optional[Dict[str, Any]] = None) -> str:
    """Simple text-node fixes that also apply to front/back matter.

    The copyright lines hold for every book. Book-specific pairs come from
    ``book_text_fixes`` in reader-repairs.yaml; generic term casing comes from
    ``reader_terms``.
    """
    fixes = book_fixes or {}
    text_pairs = list(COPYRIGHT_PAIRS) + [tuple(p) for p in fixes.get("text", [])]

    def transform(text: str) -> str:
        for old, new in text_pairs:
            text = text.replace(old, new)
        return text

    raw = _map_text_nodes(raw, transform)
    for old, new in _reader_repairs().get("reader_terms", []):
        raw = _map_text_nodes(raw, lambda text, o=old, n=new: _replace_case_preserving(text, o, n))
    for old, new in fixes.get("raw", []):
        raw = raw.replace(old, new)
    for pattern, repl in fixes.get("raw_regex", []):
        raw = re.sub(pattern, repl, raw, flags=re.IGNORECASE)
    for old, new in fixes.get("raw_after", []):
        raw = raw.replace(old, new)
    return raw


def clean_artefacts(raw: str, counts: Dict[str, int]) -> Tuple[str, int]:
    """Remove known translation artefacts and repair punctuation spacing."""
    changes = 0

    def transform(text: str) -> str:
        nonlocal changes
        before = text
        text = text.replace("compre[end]ção", "compreensão")
        text = text.replace("[...]", "alguém")
        text = text.replace("planta] como", "planta, como")
        text = text.replace("]", "")
        text = text.replace("Balmungconstruído", "Balmung, construído")
        text = text.replace("procureiporSir", "procurei por Sir")
        text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
        text = re.sub(r",\s*([?!])", r"\1", text)
        # Missing space after a full stop before a capital: "fim.Não"
        text = re.sub(r"(?<=[a-zà-ÿ])\.(?=[A-ZÀ-Ú])", ". ", text)
        text = re.sub(r"([!?])(?=[A-ZÀ-Ú])", r"\1 ", text)
        text = text.replace("DELE Assim", "DELE. Assim")
        text = re.sub(r"\s{2,}", " ", text)
        if text != before:
            changes += 1
        return text

    raw, _ = _replace_text_nodes(raw, transform)
    # Artefacts split by inline markup cannot be fixed at the text-node level.
    raw = raw.replace("compre[end", "compre")
    raw = re.sub(r",\s*</i>\?", "</i>?", raw)
    raw = re.sub(r",\s*</i>!", "</i>!", raw)
    counts["artefact_paragraphs"] = counts.get("artefact_paragraphs", 0) + changes
    return raw, changes


# Chapter headings per book live in reader-repairs.yaml, under "headings".

JOIN_OVERRIDES: Sequence[Tuple[str, str]] = (
    ("seguia o design", "Parei"),
)


def fix_headings(
    raw: str, href: str, headings: Optional[Dict[str, str]] = None
) -> Tuple[str, List[str]]:
    headings = headings or {}
    changes: List[str] = []
    filename = href.rsplit("/", 1)[-1]

    def replace_title(match: re.Match) -> str:
        opening, inner, closing = match.group(1), match.group(2), match.group(3)
        text = re.sub(r"\s+", " ", strip_tags(inner)).strip()
        text = re.sub(r"^[–—-]\s*", "", text)
        if filename in headings:
            text = headings[filename]
        elif text == "O MUNDO SOMBrio":
            text = "O MUNDO SOMBRIO"
        elif text == "DESTRUIDO":
            text = "DESTRUÍDO"
        if text != re.sub(r"\s+", " ", strip_tags(inner)).strip():
            changes.append(f"{filename}: {strip_tags(inner).strip()!r} -> {text!r}")
        return f"{opening}{text}{closing}"

    raw = re.sub(
        r'(<h1\b[^>]*class="[^"]*x03-Chapter-Title[^"]*"[^>]*>)(.*?)(</h1\s*>)',
        replace_title,
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # SCAP duplication in front matter: C<span class="SCAP">ÍNDICE</span>
    if "06_Contents.xhtml" in href:
        raw = raw.replace(
            'C<span class="SCAP">ÍNDICE</span>',
            '<span class="SCAP">S</span>UMÁRIO',
        )
        changes.append("06_Contents.xhtml: SUMÁRIO")
    if "07_Acknowledgments.xhtml" in href:
        raw = raw.replace(
            'A<span class="SCAP">AGRADECIMENTOS</span>',
            '<span class="SCAP">A</span>GRADECIMENTOS',
        )
        changes.append("07_Acknowledgments.xhtml: AGRADECIMENTOS")
    if "91_Lexicon.xhtml" in href:
        raw = raw.replace(">LEXICON<", ">LÉXICO<")
        changes.append("91_Lexicon.xhtml: LÉXICO")
    return raw, changes


def _title_case(value: str) -> str:
    small = {
        "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da",
        "dos", "das", "em", "no", "na", "nos", "nas", "por", "para", "com",
        "e", "ou", "que", "se", "ao", "aos", "à", "às", "como",
    }
    words = value.lower().split()
    if not words:
        return value
    out = []
    for index, word in enumerate(words):
        if index == 0 or index == len(words) - 1 or word not in small:
            out.append(word[:1].upper() + word[1:])
        else:
            out.append(word)
    return " ".join(out)


def _chapter_label(heading: str) -> str:
    return _title_case(heading)


def _chapter_number(raw: str) -> str:
    match = re.search(r"CAP[IÍ]TULO\s+(\d+)", strip_tags(raw), re.IGNORECASE)
    return match.group(1) if match else ""


def _label_for_document(filename: str) -> Optional[str]:
    """Front, back and extra matter label for a document, matched by its file name keyword."""
    if "_chapter_" in filename.lower():
        return None
    for keyword, label in FRONT_MATTER + BACK_MATTER + EXTRA_LABELS:
        if keyword.lower() in filename.lower():
            return label
    return None


def localise_document_title(raw: str, href: str, chapter_titles: Dict[str, str]) -> str:
    filename = href.rsplit("/", 1)[-1]
    label = None
    if filename in chapter_titles:
        number = _chapter_number(raw)
        label = f"Capítulo {number}: {chapter_titles[filename]}" if number else chapter_titles[filename]
    else:
        label = _label_for_document(filename)
    if not label:
        return raw
    match = TITLE_RE.search(raw)
    if not match:
        return raw
    return raw[: match.start(1)] + html.escape(label) + raw[match.end(1) :]


def _normalise_package_language(opf: str) -> str:
    """Align the package xml:lang with the translated dc:language."""
    if re.search(
        r"<dc:language\b[^>]*>\s*pt-BR\s*</dc:language\s*>", opf, re.IGNORECASE
    ):
        opf = re.sub(
            r'(<package\b[^>]*\bxml:lang=")[^"]*(")',
            r"\g<1>pt-BR\g<2>",
            opf,
            count=1,
            flags=re.IGNORECASE,
        )
    return opf


def _package_title(source_path: str) -> str:
    """Return the translated dc:title so the TOC matches the package."""
    with zipfile.ZipFile(source_path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".opf"):
                continue
            opf = archive.read(name).decode("utf-8", "replace")
            match = re.search(
                r"<dc:title\b[^>]*>(.*?)</dc:title\s*>",
                opf,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
    return ""


def _read_chapter_titles(
    source_path: str, headings: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    titles: Dict[str, str] = {}
    with zipfile.ZipFile(source_path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith((".xhtml", ".html")) or "_Chapter_" not in name:
                continue
            raw = archive.read(name).decode("utf-8", "replace")
            match = re.search(
                r'<h1\b[^>]*class="[^"]*x03-Chapter-Title[^"]*"[^>]*>(.*?)</h1\s*>',
                raw,
                re.IGNORECASE | re.DOTALL,
            )
            if not match:
                continue
            heading = re.sub(r"\s+", " ", strip_tags(match.group(1))).strip()
            heading = re.sub(r"^[–—-]\s*", "", heading)
            heading = (headings or {}).get(name.rsplit("/", 1)[-1], heading)
            if heading == "O MUNDO SOMBrio":
                heading = "O MUNDO SOMBRIO"
            if heading == "DESTRUIDO":
                heading = "DESTRUÍDO"
            titles[name.rsplit("/", 1)[-1]] = _chapter_label(heading)
    return titles


def _localise_nav(nav: str, labels: Dict[str, str], book_title: str = "") -> str:
    if book_title:
        nav = re.sub(
            r"<title\b[^>]*>.*?</title\s*>",
            lambda match: f"<title>{html.escape(book_title)}</title>",
            nav,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    nav = nav.replace("<h1>Contents</h1>", "<h1>Sumário</h1>")
    toc = re.search(r'<nav\b[^>]*epub:type="toc"[^>]*>', nav, re.IGNORECASE)
    if toc:
        start = toc.start()
        end = nav.find("</nav>", toc.end())
        if end > start:
            block = nav[start:end]

            def replace_link(match: re.Match) -> str:
                opening, href, inner, closing = match.group(1), match.group(2), match.group(3), match.group(4)
                key = href.split("#")[0].rsplit("/", 1)[-1]
                label = labels.get(key)
                if not label:
                    return match.group(0)
                return f"{opening}{html.escape(label)}{closing}"

            block = re.sub(
                r'(<a\b[^>]*href="([^"]+)"[^>]*>)(.*?)(</a\s*>)',
                replace_link,
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            nav = nav[:start] + block + nav[end:]
    for old, new in (
        (">Cover<", ">Capa<"),
        (">Title Page<", ">Página de título<"),
        (">Copyright<", ">Direitos autorais<"),
        (">Dedication<", ">Dedicação<"),
        (">Table of Contents<", ">Sumário<"),
        (">Start<", ">Início<"),
        (">Acknowledgments<", ">Agradecimentos<"),
        (">Lexicon<", ">Léxico<"),
    ):
        nav = nav.replace(old, new)
    return nav


def _localise_ncx(ncx: str, labels: Dict[str, str], book_title: str = "") -> str:
    if book_title:
        ncx = re.sub(
            r"<docTitle\b[^>]*>\s*<text>.*?</text>\s*</docTitle\s*>",
            lambda match: f"<docTitle><text>{html.escape(book_title)}</text></docTitle>",
            ncx,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    start = ncx.find("<navMap>")
    end = ncx.find("</navMap>", start)
    if start < 0 or end < 0:
        return ncx
    block = ncx[start:end]

    def replace_navpoint(match: re.Match) -> str:
        point = match.group(0)
        content = re.search(r'<content\b[^>]*src="([^"]+)"', point)
        if not content:
            return point
        key = content.group(1).split("#")[0].rsplit("/", 1)[-1]
        label = labels.get(key)
        if not label:
            return point
        return re.sub(r"<text>.*?</text>", f"<text>{html.escape(label)}</text>", point, count=1, flags=re.DOTALL)

    block = re.sub(r"<navPoint\b.*?</navPoint>", replace_navpoint, block, flags=re.DOTALL)
    ncx = ncx[:start] + block + ncx[end:]
    for old, new in (
        ("<text>Cover</text>", "<text>Capa</text>"),
        ("<text>Title Page</text>", "<text>Página de título</text>"),
        ("<text>Copyright</text>", "<text>Direitos autorais</text>"),
        ("<text>Dedication</text>", "<text>Dedicação</text>"),
        ("<text>Table of Contents</text>", "<text>Sumário</text>"),
        ("<text>Start</text>", "<text>Início</text>"),
        ("<text>Acknowledgments</text>", "<text>Agradecimentos</text>"),
        ("<text>Lexicon</text>", "<text>Léxico</text>"),
    ):
        ncx = ncx.replace(old, new)
    return ncx


# Front and back matter, matched by a keyword in the file name, so each book's own
# numbering works. Chapter files never match (see _matched_document).
FRONT_MATTER = [tuple(p) for p in _reader_repairs().get("labels", {}).get("front", [])]
BACK_MATTER = [tuple(p) for p in _reader_repairs().get("labels", {}).get("back", [])]
EXTRA_LABELS = [tuple(p) for p in _reader_repairs().get("labels", {}).get("extra", [])]


def _matched_document(names: Sequence[str], keyword: str) -> Optional[str]:
    for name in names:
        if "_chapter_" not in name.lower() and keyword.lower() in name.lower():
            return name
    return None


def _matched_entries(names: Sequence[str], table: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for keyword, label in table:
        name = _matched_document(names, keyword)
        if name is not None:
            entries.append((name, label))
    return entries


def _build_contents_page(
    original: str, chapter_titles: Dict[str, str], document_names: Iterable[str]
) -> str:
    names = list(document_names)
    front = _matched_entries(names, FRONT_MATTER)
    back = _matched_entries(names, BACK_MATTER)
    lines = ['<div>', '<h1 class="x01-FM-Head">SUMÁRIO</h1>']
    for href, label in front:
        lines.append(
            f'<div class="x01-FM-Contents-FL"><a href="{href}"><i>{html.escape(label)}</i></a></div>'
        )
    for filename in sorted(chapter_titles):
        if "_Chapter_" not in filename:
            continue
        number_match = re.search(r"_Chapter_(\d+)_", filename)
        if not number_match:
            continue
        number = number_match.group(1)
        lines.append(
            f'<div class="x01-FM-Contents-Space"><a href="{filename}">'
            f"Capítulo {number}: {html.escape(chapter_titles[filename])}</a></div>"
        )
    for href, label in back:
        lines.append(
            f'<div class="x01-FM-Contents-Space"><a href="{href}">{html.escape(label)}</a></div>'
        )
    lines.append("</div>")
    body = "\n".join(lines)
    match = re.search(r"(<body\b[^>]*>)(.*?)(</body\s*>)", original, re.IGNORECASE | re.DOTALL)
    if not match:
        return original
    return original[: match.start(2)] + body + original[match.end(2) :]


READING_CSS = """

/* TBL reader layout: KOReader/Kindle-friendly defaults. */
html {
    -webkit-hyphens: auto;
    hyphens: auto;
    adobe-hyphenate: auto;
}
body {
    line-height: 1.5;
}
p.x04-Body-Text,
p.x04-Body-Text-FL,
p.x03-CO-Body-Text {
    text-align: justify;
}
h1.x03-Chapter-Title + p.x04-Body-Text,
h1.x03-Chapter-Title + p.x03-CO-Body-Text,
p.x03-CO-Body-Text + p.x04-Body-Text,
p.x04-Space-Break-FL + p.x04-Body-Text {
    text-indent: 0;
}
"""


def _add_reading_css(css: str) -> str:
    if "TBL reader layout" in css:
        return css
    return css.rstrip() + READING_CSS


def repair_reading_epub(
    source_path: str,
    output_path: str,
    *,
    apply_terms: bool = True,
    queue_title: str = "",
) -> Dict[str, object]:
    """Write a reader-repaired copy of ``source_path``.

    ``queue_title`` is the book's English title in the queue. It selects the
    book's chapter headings in ``reader-repairs.yaml``; the EPUB's own title is
    already translated, so it cannot be used for that.
    """
    source_path = os.path.abspath(source_path)
    output_path = os.path.abspath(output_path)
    if source_path == output_path:
        raise ValueError("source and output must be different files")
    output_dir = os.path.dirname(output_path) or "."
    os.makedirs(output_dir, exist_ok=True)

    headings = _reader_repairs().get("headings", {}).get(queue_title, {})
    chapter_titles = _read_chapter_titles(source_path, headings)
    with zipfile.ZipFile(source_path, "r") as probe:
        document_names = [
            os.path.basename(name)
            for name in probe.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm"))
        ]
    book_title = _package_title(source_path)
    report = RepairReport(source=source_path, output=output_path)
    term_counts: Dict[str, int] = {}

    fd, temp_path = tempfile.mkstemp(prefix=".epub-reading-", suffix=".epub", dir=output_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(source_path, "r") as source, zipfile.ZipFile(
            temp_path, "w", zipfile.ZIP_DEFLATED
        ) as target:
            for item in source.infolist():
                data = source.read(item.filename)
                name = item.filename
                if name.endswith("_nav.xhtml"):
                    nav = data.decode("utf-8", "replace")
                    labels = _nav_labels(chapter_titles, document_names)
                    data = _localise_nav(nav, labels, book_title).encode("utf-8")
                elif name.lower().endswith(".ncx"):
                    ncx = data.decode("utf-8", "replace")
                    labels = _nav_labels(chapter_titles, document_names)
                    data = _localise_ncx(ncx, labels, book_title).encode("utf-8")
                elif name.lower().endswith(".opf"):
                    opf = data.decode("utf-8", "replace")
                    data = _normalise_package_language(opf).encode("utf-8")
                elif name.lower().endswith((".xhtml", ".html", ".htm")):
                    raw = data.decode("utf-8", "replace")
                    report.documents += 1
                    raw, straight_changed, warnings = normalise_straight_quotes(raw)
                    report.straight_quote_paragraphs += straight_changed
                    report.warnings.extend(warnings)
                    raw, merged = merge_split_paragraphs(raw)
                    report.merged += merged
                    raw, converted = convert_dialogue_quotes(raw)
                    report.quote_paragraphs += converted
                    raw, split = split_dialogue_paragraphs(raw)
                    report.artefact_changes["split_dialogue_paragraphs"] = (
                        report.artefact_changes.get("split_dialogue_paragraphs", 0) + split
                    )
                    if apply_terms:
                        raw, _ = apply_sun_eater_terms(raw, term_counts)
                    raw, _ = clean_artefacts(raw, report.artefact_changes)
                    raw = global_text_fixes(raw, _book_text_fixes(queue_title))
                    raw, heading_changes = fix_headings(raw, name, headings)
                    report.heading_changes.extend(heading_changes)
                    raw = localise_document_title(raw, name, chapter_titles)
                    if name.endswith("06_Contents.xhtml"):
                        raw = _build_contents_page(raw, chapter_titles, document_names)
                    if "[" in strip_tags(raw):
                        report.warnings.append(f"unresolved '[' in {name}")
                    data = raw.encode("utf-8")
                elif name.lower().endswith(".css"):
                    css = data.decode("utf-8", "replace")
                    data = _add_reading_css(css).encode("utf-8")
                target.writestr(item, data)
        os.replace(temp_path, output_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    report.term_changes = term_counts
    return report.to_dict()


def _nav_labels(
    chapter_titles: Dict[str, str], document_names: Iterable[str] = ()
) -> Dict[str, str]:
    names = list(document_names)
    labels: Dict[str, str] = {}
    for keyword, label in FRONT_MATTER + BACK_MATTER + EXTRA_LABELS:
        name = _matched_document(names, keyword)
        if name is not None:
            labels[name] = label
    for filename, title in chapter_titles.items():
        match = re.search(r"_Chapter_(\d+)_", filename)
        if match:
            labels[filename] = f"Capítulo {match.group(1)}: {title}"
    return labels
