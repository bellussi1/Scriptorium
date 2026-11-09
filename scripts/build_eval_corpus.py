"""Build the evaluation corpus, probes and long chapters.

This replaces the 30-excerpt Fase D corpus with a larger, auditable set:

- Farseer dev/test excerpts, paragraph-aligned against the official PT-BR
  editions, balanced across seven categories;
- name and terminology probes for Farseer (official reference) and for
  Gwynne/Abercrombie (provisional glossary consistency);
- three long Farseer chapters in the 3-5k word range for chunking tests;
- a machine-readable manifest and an audit of the old 30 excerpts.

Copyrighted text stays under data/benchmark (gitignored). Run:
    python scripts/build_eval_corpus.py
    python scripts/build_eval_corpus.py --preview 5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.literary.epub import count_words, iter_spine_documents, read_epub  # noqa: E402
from src.literary.resources import compile_for_book, load_tree  # noqa: E402

CALIBRE = Path(r"C:\Users\Bellussi\Biblioteca do calibre")
OUT = ROOT / "data" / "benchmark" / "literary"
RESOURCES = ROOT / "literary-resources"

WORD_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)
NAME_RE = re.compile(r"\b[A-ZÀ-Ý][a-zà-ÿ'’\-]{2,}\b")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
SENT_RE = re.compile(r"[.!?]+[\s”\"’']*")
DIALOGUE_START = ('"', "“", "‘", "'", "—")
DIALOGUE_END = '.!?”"’…—:;'
SKIP_NAMES = {
    "The", "A", "An", "He", "She", "It", "They", "We", "I", "But", "And",
    "Then", "When", "If", "As", "At", "In", "On", "For", "With", "His",
    "Her", "Their", "This", "That", "These", "Those", "There", "What",
    "Who", "Why", "How", "Where", "Not", "No", "Yes", "Chapter", "Part",
    "Book", "Prologue", "Epilogue", "One", "Two", "Three", "Four", "Five",
    "Six", "Seven", "Eight", "Nine", "Ten", "Mr", "Mrs", "Miss", "Sir",
    "God", "Lord", "Lady", "King", "Queen", "Prince", "Princess",
}
THOUGHT_WORDS = {
    "thought", "think", "wondered", "wonder", "remembered", "remember",
    "realized", "realise", "realised", "felt", "feared", "hoped", "wished",
    "knew", "know", "supposed", "understood", "decided", "considered",
}
ACTION_WORDS = {
    "ran", "run", "struck", "strike", "grabbed", "grab", "fell", "fall",
    "sword", "blade", "blood", "fight", "fought", "kill", "killed", "hit",
    "shoved", "pulled", "pushed", "leapt", "leaped", "charged", "blocked",
    "dodged", "wound", "wounded", "screamed", "shouted", "attack", "battle",
    "cut", "thrust", "swung", "swing", "axe", "spear", "arrow", "bow",
    "horse", "rode", "ride", "chase", "chased", "fled", "grip", "grabbed",
    "wrestled", "slammed", "crashed", "spurred", "reined", "parried",
    "hacked", "stabbed", "wrenched", "tackled", "kicked", "punched",
    "seized", "lunged", "drew", "loosed", "fired", "shield", "shields",
    "armor", "armour", "helmet", "corpse", "dead", "died", "dying",
    "struggled", "rolled", "sprang", "clung", "hauled", "dragged",
}
SENSORY_WORDS = {
    "saw", "see", "looked", "look", "watched", "heard", "hear", "smelled",
    "smell", "tasted", "felt", "cold", "warm", "hot", "light", "dark",
    "stone", "wood", "earth", "rain", "snow", "wind", "fire", "smoke",
    "green", "grey", "gray", "red", "black", "white", "silver", "gold",
}
IRONY_WORDS = {
    "of course", "naturally", "fortunately", "no doubt", "as usual",
    "i suppose", "perfect", "fine", "indeed", "rather", "to be sure",
    "not that", "how fortunate", "how kind", "surely",
}
BOOKS = [
    {
        "slug": "assassins-apprentice",
        "title": "Assassin's Apprentice",
        "author": "Robin Hobb",
        "order": 1,
        "en": CALIBRE / "Robin Hobb/Assassin's Apprentice (336)/Assassin's Apprentice - Robin Hobb.epub",
        "pt": CALIBRE / "Robin Hobb/O Aprendiz de Assassino (94)/O Aprendiz de Assassino - Robin Hobb.epub",
    },
    {
        "slug": "royal-assassin",
        "title": "Royal Assassin",
        "author": "Robin Hobb",
        "order": 2,
        "en": CALIBRE / "Robin Hobb/Royal Assassin (329)/Royal Assassin - Robin Hobb.epub",
        "pt": CALIBRE / "Robin Hobb/O Assassino do Rei (92)/O Assassino do Rei - Robin Hobb.epub",
    },
    {
        "slug": "assassins-quest",
        "title": "Assassin's Quest",
        "author": "Robin Hobb",
        "order": 3,
        "en": CALIBRE / "Robin Hobb/Assassin's Quest (338)/Assassin's Quest - Robin Hobb.epub",
        "pt": CALIBRE / "Robin Hobb/A Furia do Assassino (71)/A Furia do Assassino - Robin Hobb.epub",
    },
]
PROBE_BOOKS = [
    {
        "slug": "malice",
        "title": "Malice",
        "author": "John Gwynne",
        "series": "The Banished Lands",
        "path": CALIBRE / "John Gwynne/Malice (354)/Malice - John Gwynne.epub",
        "author_slug": "john-gwynne",
        "universe": "the-banished-lands",
        "subseries": "the-faithful-and-the-fallen",
    },
    {
        "slug": "a-time-of-dread",
        "title": "A Time of Dread",
        "author": "John Gwynne",
        "series": "The Banished Lands",
        "path": CALIBRE / "John Gwynne/A Time of Dread (345)/A Time of Dread - John Gwynne.epub",
        "author_slug": "john-gwynne",
        "universe": "the-banished-lands",
        "subseries": "of-blood-and-bone",
    },
    {
        "slug": "a-little-hatred",
        "title": "A Little Hatred",
        "author": "Joe Abercrombie",
        "series": "The First Law",
        "path": CALIBRE / "Joe Abercrombie/A Little Hatred (346)/A Little Hatred - Joe Abercrombie.epub",
        "author_slug": "joe-abercrombie",
        "universe": "the-first-law",
        "subseries": "the-age-of-madness",
    },
]
CATEGORIES = [
    "dialogue", "introspection", "description", "action",
    "long_syntax", "irony", "terminology",
]
# Manually reviewed pairs that the surface heuristics still accept. The
# signature is (book_slug, en_href, en_paragraph, pt_href, pt_paragraph).
BLACKLIST = {
    (
        "assassins-apprentice",
        "OEBPS/Hobb_9780553897487_epub_c23_r1.htm",
        54,
        "Text/part0027.html",
        99,
    ),
}


@dataclass
class TermMatch:
    source: str
    target: str
    category: str
    forbidden: List[str] = field(default_factory=list)


@dataclass
class Candidate:
    id: str
    book_slug: str
    book: str
    author: str
    chapter_index: int
    chapter_title: str
    category: str
    text: str
    reference_pt: str
    en_href: str
    pt_href: str
    en_paragraph: int
    pt_paragraph: int
    alignment_score: float
    ratio: float
    shared: List[str]
    confidence: str
    term_matches: List[TermMatch] = field(default_factory=list)
    character_matches: List[TermMatch] = field(default_factory=list)
    character_pool: List[str] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return count_words(self.text)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "book": self.book,
            "book_slug": self.book_slug,
            "author": self.author,
            "chapter_index": self.chapter_index,
            "chapter_title": self.chapter_title,
            "category": self.category,
            "chapter_href": self.en_href,
            "text": self.text,
            "reference_pt": self.reference_pt,
            "source_language": "en",
            "target_language": "pt-BR",
            "word_count": self.word_count,
            "alignment": {
                "en_href": self.en_href,
                "pt_href": self.pt_href,
                "en_paragraph": self.en_paragraph,
                "pt_paragraph": self.pt_paragraph,
                "score": round(self.alignment_score, 3),
                "ratio": round(self.ratio, 3),
                "shared": self.shared[:8],
                "confidence": self.confidence,
            },
            "expected_terms": [
                {"source": term.source, "target": term.target, "category": term.category}
                for term in self.term_matches
            ],
            "characters": [term.target for term in self.character_matches],
            "notes": "auto-aligned; review before treating the pair as gold",
        }


def _paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _is_dialogue(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    if stripped.startswith(DIALOGUE_START):
        return True
    quotes = sum(stripped.count(char) for char in ('"', "“", "”", "‘", "’"))
    dashes = stripped.count("—")
    return quotes >= 2 or dashes >= 2


def _names(text: str) -> set[str]:
    names = {match.group(0).casefold() for match in NAME_RE.finditer(text)}
    names |= set(NUMBER_RE.findall(text))
    skip = {value.casefold() for value in SKIP_NAMES}
    return {name for name in names if name not in skip}


def _rare_tokens(text: str) -> set[str]:
    return {
        word.casefold()
        for word in WORD_RE.findall(text)
        if len(word) >= 6 and word.casefold() not in {"himself", "herself", "because", "through", "without", "before", "after", "should", "would", "could"}
    }


def _term_patterns(terms: Sequence[Any]) -> List[Tuple[str, re.Pattern[str], TermMatch]]:
    patterns = []
    for term in terms:
        for form in term.source_forms():
            if not form.strip():
                continue
            flags = 0 if form[0].isupper() else re.IGNORECASE
            pattern = re.compile(r"(?<!\w)" + re.escape(form) + r"(?!\w)", flags)
            target = term.target_for_form(form)
            patterns.append(
                (
                    form,
                    pattern,
                    TermMatch(
                        source=form,
                        target=target,
                        category=term.category,
                        forbidden=list(term.forbidden or []),
                    ),
                )
            )
    patterns.sort(key=lambda item: len(item[0]), reverse=True)
    return patterns


def _match_terms(text: str, patterns: Sequence[Tuple[str, re.Pattern[str], TermMatch]]) -> List[TermMatch]:
    occupied: List[Tuple[int, int]] = []
    matches: List[TermMatch] = []
    for form, pattern, term in patterns:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < existing_end and end > existing_start for existing_start, existing_end in occupied):
                continue
            occupied.append((start, end))
            matches.append(term)
            break
    # Deduplicate by source/target while preserving the first appearance.
    seen = set()
    result = []
    for term in matches:
        key = (term.source, term.target)
        if key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result


def _style(text: str) -> Dict[str, float]:
    sentences = [s.strip() for s in SENT_RE.split(text) if s.strip()]
    lengths = [len(WORD_RE.findall(s)) for s in sentences]
    lengths = [value for value in lengths if value]
    if not lengths:
        return {"median": 0, "p90": 0}
    ordered = sorted(lengths)
    percentile = lambda fraction: ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))]
    return {
        "median": percentile(0.5),
        "p90": percentile(0.9),
        "mean": round(sum(lengths) / len(lengths), 2),
        "dialogue_pct": round(100 * sum(1 for s in sentences if s.lstrip().startswith(DIALOGUE_START)) / len(sentences), 1),
    }


def _classify(text: str, term_matches: Sequence[TermMatch]) -> str:
    words = WORD_RE.findall(text)
    if not words:
        return "description"
    lower = text.casefold()
    word_count = len(words)
    stats = _style(text)
    dialogue = _is_dialogue(text)
    sentences = [s.strip() for s in SENT_RE.split(text) if s.strip()]
    dialogue_sentences = sum(1 for s in sentences if s.lstrip().startswith(DIALOGUE_START))
    dialogue_ratio = dialogue_sentences / max(1, len(sentences))
    first_person = sum(1 for w in words if w.casefold() in {"i", "my", "me", "mine", "myself"})
    thought = sum(1 for w in words if w.casefold() in THOUGHT_WORDS)
    action = sum(1 for w in words if w.casefold() in ACTION_WORDS)
    sensory = sum(1 for w in words if w.casefold() in SENSORY_WORDS)
    irony = sum(1 for phrase in IRONY_WORDS if phrase in lower)
    non_character = [term for term in term_matches if term.category != "character"]
    term_density = len(non_character) / max(1, word_count)
    if len(non_character) >= 2 and term_density >= 0.025:
        return "terminology"
    if action >= 4 and dialogue_ratio < 0.5 and stats["median"] <= 14:
        return "action"
    if dialogue and dialogue_ratio >= 0.35:
        return "dialogue"
    if action >= 3 and dialogue_ratio < 0.35 and stats["median"] <= 15:
        return "action"
    if first_person >= 2 and thought >= 1:
        return "introspection"
    if irony >= 1 and (first_person >= 1 or dialogue):
        return "irony"
    if stats["median"] >= 15 or stats["p90"] >= 30:
        return "long_syntax"
    if sensory >= 3:
        return "description"
    if dialogue:
        return "dialogue"
    if first_person >= 2:
        return "introspection"
    return "description"


def _match_score(en_text: str, pt_text: str, i: int, j: int, n: int, m: int) -> float:
    en_words = max(1, count_words(en_text))
    pt_words = max(1, count_words(pt_text))
    ratio = pt_words / en_words
    if ratio < 0.45 or ratio > 1.9:
        return -4.0
    en_names = _names(en_text)
    pt_names = _names(pt_text)
    shared_names = en_names & pt_names
    shared_rare = _rare_tokens(en_text) & _rare_tokens(pt_text)
    score = 2.2 * len(shared_names)
    score += 0.3 * min(6, len(shared_rare))
    score += 1.4 * max(0.0, 1.0 - abs(ratio - 1.05) / 0.55)
    score += 0.4 * (1.0 - abs((i / max(1, n - 1)) - (j / max(1, m - 1))))
    if _is_dialogue(en_text) == _is_dialogue(pt_text):
        score += 0.7
    else:
        score -= 0.9
    return score


def _align_chapter(
    en_doc: Dict[str, Any],
    pt_doc: Dict[str, Any],
    chapter_index: int,
    chapter_title: str,
    book: Dict[str, Any],
    patterns: Sequence[Tuple[str, re.Pattern[str], TermMatch]],
) -> List[Candidate]:
    en_paras = [
        p for p in _paragraphs(en_doc.get("text") or "")
        if 12 <= count_words(p) <= 320
        and re.match(r"^[A-ZÀ-Ý“\"'‘—–\-]", p)
        and p[-1] in DIALOGUE_END
    ]
    pt_paras = [
        p for p in _paragraphs(pt_doc.get("text") or "")
        if 10 <= count_words(p) <= 360
        and re.match(r"^[A-ZÀ-Ý“\"'‘—–\-]", p)
        and p[-1] in DIALOGUE_END
    ]
    n, m = len(en_paras), len(pt_paras)
    if n < 3 or m < 3:
        return []
    gap = -0.9
    dp = [[float("-inf")] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap
        back[i][0] = "up"
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + gap
        back[0][j] = "left"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diagonal = dp[i - 1][j - 1] + _match_score(en_paras[i - 1], pt_paras[j - 1], i - 1, j - 1, n, m)
            up = dp[i - 1][j] + gap
            left = dp[i][j - 1] + gap
            best = max(diagonal, up, left)
            dp[i][j] = best
            back[i][j] = "diagonal" if best == diagonal else ("up" if best == up else "left")
    pairs = []
    i, j = n, m
    while i > 0 and j > 0:
        direction = back[i][j]
        if direction == "diagonal":
            en_text = en_paras[i - 1]
            pt_text = pt_paras[j - 1]
            score = _match_score(en_text, pt_text, i - 1, j - 1, n, m)
            shared = sorted(_names(en_text) & _names(pt_text))
            ratio = count_words(pt_text) / max(1, count_words(en_text))
            if score >= 1.0 and 0.5 <= ratio <= 1.8:
                dialogue_match = _is_dialogue(en_text) == _is_dialogue(pt_text)
                if shared and dialogue_match and 0.7 <= ratio <= 1.4:
                    confidence = "high"
                elif (len(shared) >= 2 or len(_rare_tokens(en_text) & _rare_tokens(pt_text)) >= 3) and dialogue_match:
                    confidence = "medium"
                elif dialogue_match and 0.8 <= ratio <= 1.25:
                    confidence = "medium"
                else:
                    confidence = "low"
                if confidence != "low":
                    signature = (
                        book["slug"],
                        str(en_doc.get("href", "")),
                        i - 1,
                        str(pt_doc.get("href", "")),
                        j - 1,
                    )
                    if signature in BLACKLIST:
                        i -= 1
                        j -= 1
                        continue
                    matches = _match_terms(en_text, patterns)
                    characters = [term for term in matches if term.category == "character"]
                    pairs.append(
                        Candidate(
                            id=f"{book['slug']}-{chapter_index:02d}-{i - 1:04d}",
                            book_slug=book["slug"],
                            book=book["title"],
                            author=book["author"],
                            chapter_index=chapter_index,
                            chapter_title=chapter_title,
                            category=_classify(en_text, matches),
                            text=en_text,
                            reference_pt=pt_text,
                            en_href=en_doc.get("href", ""),
                            pt_href=pt_doc.get("href", ""),
                            en_paragraph=i - 1,
                            pt_paragraph=j - 1,
                            alignment_score=score,
                            ratio=ratio,
                            shared=shared,
                            confidence=confidence,
                            term_matches=matches,
                            character_matches=characters,
                            character_pool=sorted(
                                {term.target for _, _, term in patterns if term.category == "character"}
                            ),
                        )
                    )
            i -= 1
            j -= 1
        elif direction == "up":
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _content_docs(path: Path) -> List[Dict[str, Any]]:
    docs = []
    for doc in iter_spine_documents(str(path)):
        text = doc.get("text") or ""
        href = str(doc.get("href") or "").lower()
        if count_words(text) < 900:
            continue
        if any(marker in href for marker in ("bm", "back", "ack", "toc", "title", "copyright", "dedication")):
            continue
        docs.append(doc)
    return docs


def _toc_map(path: Path) -> Dict[str, str]:
    info = read_epub(str(path))
    return {
        str(item.get("href") or "").lower(): str(item.get("title") or "")
        for item in info.toc
    }


def build_farseer() -> Tuple[List[Candidate], Dict[str, Any]]:
    tree = load_tree(str(RESOURCES))
    all_candidates: List[Candidate] = []
    diagnostics: Dict[str, Any] = {}
    for book in BOOKS:
        if not book["en"].exists() or not book["pt"].exists():
            raise FileNotFoundError(book["slug"])
        compiled = compile_for_book(
            tree, "robin-hobb", "realm-of-the-elderlings", "farseer", book["slug"]
        )
        patterns = _term_patterns(compiled.glossary.terms)
        en_docs = _content_docs(book["en"])
        pt_docs = _content_docs(book["pt"])
        en_toc = _toc_map(book["en"])
        pt_toc = _toc_map(book["pt"])
        pairs = min(len(en_docs), len(pt_docs))
        book_candidates = []
        for index in range(pairs):
            en_words = count_words(en_docs[index].get("text") or "")
            pt_words = count_words(pt_docs[index].get("text") or "")
            ratio = pt_words / max(1, en_words)
            if ratio < 0.65 or ratio > 1.55:
                continue
            title = en_toc.get(str(en_docs[index].get("href") or "").lower(), "")
            if not title:
                title = pt_toc.get(str(pt_docs[index].get("href") or "").lower(), "")
            if not title:
                title = f"Chapter {index + 1}"
            chapter_candidates = _align_chapter(
                en_docs[index], pt_docs[index], index, title, book, patterns
            )
            book_candidates.extend(chapter_candidates)
        all_candidates.extend(book_candidates)
        diagnostics[book["slug"]] = {
            "chapters": pairs,
            "candidates": len(book_candidates),
            "categories": dict(Counter(item.category for item in book_candidates)),
            "confidence": dict(Counter(item.confidence for item in book_candidates)),
        }
    return all_candidates, diagnostics


def _round_robin(pool: Sequence[Candidate], count: int) -> List[Candidate]:
    by_book: Dict[str, List[Candidate]] = defaultdict(list)
    for item in pool:
        by_book[item.book_slug].append(item)
    for items in by_book.values():
        items.sort(key=lambda item: (item.confidence != "high", -item.alignment_score, -len(item.term_matches)))
    order = [book["slug"] for book in BOOKS]
    chosen: List[Candidate] = []
    while len(chosen) < count and any(by_book.values()):
        for slug in order:
            if by_book[slug] and len(chosen) < count:
                chosen.append(by_book[slug].pop(0))
    return chosen


def _split_items(items: Sequence[Candidate], test_count: int, offset: int = 0) -> Tuple[List[Candidate], List[Candidate]]:
    by_book: Dict[str, List[Candidate]] = defaultdict(list)
    for item in items:
        by_book[item.book_slug].append(item)
    order = [book["slug"] for book in BOOKS]
    order = order[offset % len(order):] + order[:offset % len(order)]
    test: List[Candidate] = []
    while len(test) < test_count:
        progressed = False
        for slug in order:
            if by_book[slug] and len(test) < test_count:
                test.append(by_book[slug].pop(0))
                progressed = True
        if not progressed:
            break
    test_ids = {item.id for item in test}
    dev = [item for item in items if item.id not in test_ids]
    return dev, test


def select_corpus(candidates: Sequence[Candidate]) -> List[Candidate]:
    by_category: Dict[str, List[Candidate]] = defaultdict(list)
    for item in candidates:
        by_category[item.category].append(item)
    target = {category: 12 for category in CATEGORIES}
    selected: List[Candidate] = []
    for category in CATEGORIES:
        pool = by_category.get(category, [])
        count = min(target[category], len(pool))
        selected.extend(_round_robin(pool, count))
    # Guarantee a dev/test split within each category without overlap.
    by_selected: Dict[str, List[Candidate]] = defaultdict(list)
    for item in selected:
        by_selected[item.category].append(item)
    final: List[Candidate] = []
    for category_index, category in enumerate(CATEGORIES):
        items = by_selected.get(category, [])
        if not items:
            continue
        test_count = max(2, round(len(items) / 3))
        dev, test = _split_items(items, test_count, offset=category_index)
        final.extend(dev)
        final.extend(test)
    return final


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def _probe_payload(
    *,
    probe_id: str,
    kind: str,
    series: str,
    book: Dict[str, Any],
    text: str,
    reference: str,
    reference_kind: str,
    terms: Sequence[TermMatch],
    characters: Sequence[TermMatch],
    character_pool: Sequence[str],
    notes: str,
    reference_coverage: Optional[float] = None,
) -> Dict[str, Any]:
    expected = [
        {"source": term.source, "target": term.target, "category": term.category}
        for term in terms
    ]
    return {
        "id": probe_id,
        "kind": kind,
        "series": series,
        "book": book["title"],
        "book_slug": book["slug"],
        "author": book["author"],
        "category": "probe",
        "text": text,
        "source_language": "en",
        "target_language": "pt-BR",
        "reference_pt": reference,
        "reference_kind": reference_kind,
        "expected_terms": expected,
        "characters": [term.target for term in characters],
        "character_pool": sorted(set(character_pool)),
        "reference_coverage": reference_coverage,
        "notes": notes,
    }


def _reference_coverage(item: Candidate, terms: Sequence[TermMatch]) -> float:
    if not item.reference_pt or not terms:
        return 1.0
    reference = item.reference_pt.casefold()
    hits = sum(1 for term in terms if term.target.casefold() in reference)
    return hits / len(terms)


def build_farseer_probes(
    candidates: Sequence[Candidate], selected: Sequence[Candidate]
) -> Dict[str, List[Dict[str, Any]]]:
    selected_ids = {item.id for item in selected}
    pool = [item for item in candidates if item.id not in selected_ids]
    name_pool = [
        item for item in pool
        if 2 <= len(item.character_matches) <= 4
        and item.confidence == "high"
        and _reference_coverage(item, item.character_matches) >= 0.8
    ]
    term_pool = [
        item for item in pool
        if len([term for term in item.term_matches if term.category != "character"]) >= 2
        and item.confidence == "high"
        and _reference_coverage(
            item,
            [term for term in item.term_matches if term.category != "character"],
        ) >= 0.6
    ]
    names = _round_robin(name_pool, 25)
    terms = _round_robin(term_pool, 25)
    name_rows = []
    for index, item in enumerate(names, start=1):
        name_rows.append(
            _probe_payload(
                probe_id=f"probe-name-farseer-{index:03d}",
                kind="name",
                series="Realm of the Elderlings",
                book={"title": item.book, "slug": item.book_slug, "author": item.author},
                text=item.text,
                reference=item.reference_pt,
                reference_kind="official_pt",
                terms=item.character_matches,
                characters=item.character_matches,
                character_pool=item.character_pool,
                notes=f"aligned {item.book_slug} chapter {item.chapter_index}; official PT reference",
                reference_coverage=_reference_coverage(item, item.character_matches),
            )
        )
    term_rows = []
    for index, item in enumerate(terms, start=1):
        non_character = [term for term in item.term_matches if term.category != "character"]
        term_rows.append(
            _probe_payload(
                probe_id=f"probe-term-farseer-{index:03d}",
                kind="term",
                series="Realm of the Elderlings",
                book={"title": item.book, "slug": item.book_slug, "author": item.author},
                text=item.text,
                reference=item.reference_pt,
                reference_kind="official_pt",
                terms=non_character,
                characters=item.character_matches,
                character_pool=item.character_pool,
                notes=f"aligned {item.book_slug} chapter {item.chapter_index}; official PT reference",
                reference_coverage=_reference_coverage(item, non_character),
            )
        )
    return {"names": name_rows, "terms": term_rows}


def build_source_probes() -> Dict[str, List[Dict[str, Any]]]:
    tree = load_tree(str(RESOURCES))
    result: Dict[str, List[Dict[str, Any]]] = {"banished_terms": [], "first_law_terms": [], "banished_names": [], "first_law_names": []}
    for book in PROBE_BOOKS:
        compiled = compile_for_book(
            tree,
            book["author_slug"],
            book["universe"],
            book["subseries"],
            book["slug"],
        )
        patterns = _term_patterns(compiled.glossary.terms)
        all_characters = sorted(
            {term.target for _, _, term in patterns if term.category == "character"}
        )
        docs = _content_docs(book["path"])
        candidates: List[Tuple[str, List[TermMatch], List[TermMatch]]] = []
        for doc in docs[:25]:
            for paragraph in _paragraphs(doc.get("text") or ""):
                words = count_words(paragraph)
                if words < 40 or words > 260:
                    continue
                matches = _match_terms(paragraph, patterns)
                characters = [term for term in matches if term.category == "character"]
                non_character = [term for term in matches if term.category != "character"]
                if len(non_character) >= 1 and len(matches) >= 2:
                    candidates.append((paragraph, matches, non_character))
        candidates.sort(key=lambda item: (-len(item[2]), -len(item[1])))
        seen = set()
        selected = []
        term_limit = 15 if book["author"] == "John Gwynne" else 20
        for paragraph, matches, non_character in candidates:
            key = paragraph[:120]
            if key in seen:
                continue
            seen.add(key)
            selected.append((paragraph, matches, non_character))
            if len(selected) >= term_limit:
                break
        series_key = "banished" if book["author"] == "John Gwynne" else "first_law"
        for index, (paragraph, matches, non_character) in enumerate(selected, start=1):
            result[f"{series_key}_terms"].append(
                _probe_payload(
                    probe_id=f"probe-term-{series_key}-{index:03d}",
                    kind="term",
                    series=book["series"],
                    book=book,
                    text=paragraph,
                    reference="",
                    reference_kind="provisional_glossary",
                    terms=matches,
                    characters=[term for term in matches if term.category == "character"],
                    character_pool=all_characters,
                    notes="source-only; expected targets come from the provisional glossary",
                )
            )
        # Name probes: separate pass so term-dense passages are not reused.
        name_candidates = []
        for doc in docs[:25]:
            for paragraph in _paragraphs(doc.get("text") or ""):
                words = count_words(paragraph)
                if words < 40 or words > 260:
                    continue
                matches = _match_terms(paragraph, patterns)
                characters = [term for term in matches if term.category == "character"]
                if 2 <= len(characters) <= 4:
                    name_candidates.append((paragraph, matches, characters))
        name_candidates.sort(key=lambda item: (-len(item[2]), -len(item[1])))
        seen_names = set()
        selected_names = []
        for paragraph, matches, characters in name_candidates:
            key = paragraph[:120]
            if key in seen_names:
                continue
            seen_names.add(key)
            selected_names.append((paragraph, matches, characters))
            if len(selected_names) >= 15:
                break
        for index, (paragraph, matches, characters) in enumerate(selected_names, start=1):
            result[f"{series_key}_names"].append(
                _probe_payload(
                    probe_id=f"probe-name-{series_key}-{index:03d}",
                    kind="name",
                    series=book["series"],
                    book=book,
                    text=paragraph,
                    reference="",
                    reference_kind="provisional_glossary",
                    terms=characters,
                    characters=characters,
                    character_pool=all_characters,
                    notes="source-only; expected targets come from the provisional glossary",
                )
            )
    return result


def build_long_chapters() -> List[Dict[str, Any]]:
    tree = load_tree(str(RESOURCES))
    specs = [
        ("assassins-apprentice", 20),
        ("royal-assassin", 6),
        ("royal-assassin", 32),
    ]
    rows = []
    for book_slug, chapter_index in specs:
        book = next(item for item in BOOKS if item["slug"] == book_slug)
        compiled = compile_for_book(tree, "robin-hobb", "realm-of-the-elderlings", "farseer", book_slug)
        patterns = _term_patterns(compiled.glossary.terms)
        en_docs = _content_docs(book["en"])
        pt_docs = _content_docs(book["pt"])
        en_doc = en_docs[chapter_index]
        pt_doc = pt_docs[chapter_index]
        en_text = en_doc.get("text") or ""
        pt_text = pt_doc.get("text") or ""
        title = _toc_map(book["en"]).get(str(en_doc.get("href") or "").lower(), "")
        if not title:
            title = _toc_map(book["pt"]).get(str(pt_doc.get("href") or "").lower(), "")
        if not title:
            title = f"Chapter {chapter_index + 1}"
        rows.append(
            {
                "id": f"long-{book_slug}-{chapter_index:02d}",
                "kind": "long_chapter",
                "book": book["title"],
                "book_slug": book_slug,
                "author": book["author"],
                "chapter_index": chapter_index,
                "chapter_title": title,
                "text": en_text,
                "reference_pt": pt_text,
                "source_language": "en",
                "target_language": "pt-BR",
                "word_count": count_words(en_text),
                "reference_word_count": count_words(pt_text),
                "expected_terms": [
                    {"source": term.source, "target": term.target, "category": term.category}
                    for term in _match_terms(en_text, patterns)
                ],
                "notes": "full chapter in the 3-5k word range; use the queue chunker, not a single prompt",
            }
        )
    return rows


def audit_old_corpus() -> List[Dict[str, Any]]:
    path = OUT / "corpus_aligned_farseer.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    bad = {
        "royal-assassin-00": "source is Chivalry/Bearns dialogue; reference is a different Bearns/Rippon/Shoaks reflection paragraph",
        "royal-assassin-03": "source is the snowdrop description; reference is the party leaving the terrace",
    }
    audit = []
    for row in rows:
        verdict = "drop" if row["id"] in bad else "keep"
        audit.append(
            {
                "id": row["id"],
                "book": row.get("book", ""),
                "category": row.get("category", ""),
                "verdict": verdict,
                "reason": bad.get(row["id"], "paragraph-level content, names and length ratio match; manual review confirmed"),
            }
        )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=int, default=0)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    candidates, diagnostics = build_farseer()
    selected = select_corpus(candidates)
    # Retain the actual split assigned in select_corpus by re-running the logic.
    by_category: Dict[str, List[Candidate]] = defaultdict(list)
    for item in selected:
        by_category[item.category].append(item)
    final: List[Dict[str, Any]] = []
    for category_index, category in enumerate(CATEGORIES):
        items = by_category.get(category, [])
        if not items:
            continue
        test_count = max(2, round(len(items) / 3))
        dev_items, test_items = _split_items(items, test_count, offset=category_index)
        for item in dev_items:
            row = item.to_dict()
            row["split"] = "dev"
            final.append(row)
        for item in test_items:
            row = item.to_dict()
            row["split"] = "test"
            final.append(row)
    dev_rows = [row for row in final if row["split"] == "dev"]
    test_rows = [row for row in final if row["split"] == "test"]
    _write_jsonl(OUT / "eval_farseer_dev.jsonl", dev_rows)
    _write_jsonl(OUT / "eval_farseer_test.jsonl", test_rows)

    probes = build_farseer_probes(candidates, selected)
    source_probes = build_source_probes()
    _write_jsonl(OUT / "probes_names_farseer.jsonl", probes["names"])
    _write_jsonl(OUT / "probes_terms_farseer.jsonl", probes["terms"])
    _write_jsonl(OUT / "probes_terms_banished.jsonl", source_probes["banished_terms"])
    _write_jsonl(OUT / "probes_terms_first_law.jsonl", source_probes["first_law_terms"])
    _write_jsonl(OUT / "probes_names_banished.jsonl", source_probes["banished_names"])
    _write_jsonl(OUT / "probes_names_first_law.jsonl", source_probes["first_law_names"])

    long_chapters = build_long_chapters()
    _write_jsonl(OUT / "long_chapters_farseer.jsonl", long_chapters)
    audit = audit_old_corpus()
    _write_jsonl(OUT / "fase-d-audit.jsonl", audit)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "diagnostics": diagnostics,
        "corpus": {
            "dev": len(dev_rows),
            "test": len(test_rows),
            "total": len(final),
            "by_category": dict(Counter(row["category"] for row in final)),
            "by_split_category": {
                split: dict(Counter(row["category"] for row in rows))
                for split, rows in (("dev", dev_rows), ("test", test_rows))
            },
        },
        "probes": {
            "names_farseer": len(probes["names"]),
            "terms_farseer": len(probes["terms"]),
            "terms_banished": len(source_probes["banished_terms"]),
            "terms_first_law": len(source_probes["first_law_terms"]),
            "names_banished": len(source_probes["banished_names"]),
            "names_first_law": len(source_probes["first_law_names"]),
        },
        "long_chapters": [
            {"id": row["id"], "chapter_title": row["chapter_title"], "words": row["word_count"]}
            for row in long_chapters
        ],
        "audit": {
            "total": len(audit),
            "keep": sum(1 for row in audit if row["verdict"] == "keep"),
            "drop": sum(1 for row in audit if row["verdict"] == "drop"),
        },
        "files": [
            "eval_farseer_dev.jsonl",
            "eval_farseer_test.jsonl",
            "probes_names_farseer.jsonl",
            "probes_terms_farseer.jsonl",
            "probes_terms_banished.jsonl",
            "probes_terms_first_law.jsonl",
            "probes_names_banished.jsonl",
            "probes_names_first_law.jsonl",
            "long_chapters_farseer.jsonl",
            "fase-d-audit.jsonl",
        ],
    }
    (OUT / "eval_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if args.preview:
        for row in final[: args.preview]:
            print("=" * 100)
            print(row["id"], row["split"], row["category"], row["alignment"])
            print("EN:", row["text"][:500])
            print("PT:", row["reference_pt"][:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
