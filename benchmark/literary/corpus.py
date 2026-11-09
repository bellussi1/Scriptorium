"""Build a local literary evaluation corpus from the user's EPUBs.

The output is written to ``data/benchmark/literary/`` which is gitignored. Do
not commit copyrighted excerpts to the repository.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.literary.epub import count_words, iter_spine_documents

WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019\-][^\W\d_]+)*", re.UNICODE)


@dataclass
class Excerpt:
    id: str
    book: str
    author: str
    chapter_href: str
    category: str
    text: str
    source_language: str = "en"
    reference_pt: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _has_dialogue(paragraph: str) -> bool:
    return bool(re.match(r'^[“"\'—–-]', paragraph)) or paragraph.count('"') >= 2


def _first_person_ratio(paragraph: str) -> float:
    words = [w.casefold() for w in WORD_RE.findall(paragraph)]
    if not words:
        return 0.0
    return sum(1 for w in words if w in {"i", "me", "my", "mine", "myself"}) / len(words)


def _sensory_ratio(paragraph: str) -> float:
    words = [w.casefold() for w in WORD_RE.findall(paragraph)]
    if not words:
        return 0.0
    cues = {
        "light", "dark", "cold", "heat", "smell", "scent", "sound", "noise", "silence",
        "rain", "wind", "dust", "blood", "stone", "wood", "iron", "salt", "smoke",
        "red", "white", "black", "green", "blue", "grey", "gray", "gold",
    }
    return sum(1 for w in words if w in cues) / len(words)


def _classify(paragraph: str) -> str:
    if _has_dialogue(paragraph):
        return "dialogue"
    if _first_person_ratio(paragraph) >= 0.025:
        return "introspection"
    if _sensory_ratio(paragraph) >= 0.035:
        return "description"
    if len(WORD_RE.findall(paragraph)) >= 80 and paragraph.count(",") >= 3:
        return "long_syntax"
    return "narration"


def _pick_spread(items: List[Excerpt], count: int = 1) -> List[Excerpt]:
    """Pick up to ``count`` items spread across the list, avoiding only openings."""
    if count <= 0 or not items:
        return []
    if len(items) <= count:
        return list(items)
    if count == 1:
        return [items[len(items) // 2]]
    indices = {
        round(index * (len(items) - 1) / (count - 1)) for index in range(count)
    }
    return [items[index] for index in sorted(indices)]


def build_from_inventory(
    inventory_path: str,
    output_path: str,
    *,
    books: Optional[List[str]] = None,
    chapters_per_book: int = 3,
    per_book: int = 5,
    min_words: int = 80,
    max_words: int = 260,
) -> List[Excerpt]:
    payload = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    rows = payload.get("books", [])
    if books:
        wanted = {b.casefold() for b in books}
        rows = [row for row in rows if str(row.get("title", "")).casefold() in wanted or str(row.get("calibre_id")) in wanted]
    excerpts: List[Excerpt] = []
    for row in rows:
        epub_path = row.get("epub_path") or ""
        if not epub_path or not os.path.exists(epub_path):
            continue
        chapter_docs = [
            doc
            for doc in iter_spine_documents(epub_path)
            if count_words(doc["text"]) >= 900
        ]
        if chapters_per_book > 0 and len(chapter_docs) > chapters_per_book:
            if chapters_per_book == 1:
                indices = [len(chapter_docs) // 2]
            else:
                indices = sorted(
                    {
                        round(index * (len(chapter_docs) - 1) / (chapters_per_book - 1))
                        for index in range(chapters_per_book)
                    }
                )
            chapter_docs = [chapter_docs[index] for index in indices]

        candidates: List[Excerpt] = []
        for chapter_number, doc in enumerate(chapter_docs, start=1):
            for paragraph in _paragraphs(doc["text"]):
                count = count_words(paragraph)
                if count < min_words or count > max_words:
                    continue
                category = _classify(paragraph)
                candidates.append(
                    Excerpt(
                        id=f"{row.get('calibre_id')}-{chapter_number}-{len(candidates)}",
                        book=str(row.get("title", "")),
                        author=str(row.get("author", "")),
                        chapter_href=doc["href"],
                        category=category,
                        text=paragraph,
                        notes="auto-selected candidate; review category and continuity before use",
                    )
                )

        # Spread the selection across categories and across the chosen chapters,
        # instead of always taking the first paragraph of the first chapter.
        by_category: Dict[str, List[Excerpt]] = {}
        for candidate in candidates:
            by_category.setdefault(candidate.category, []).append(candidate)
        chosen: List[Excerpt] = []
        for category in ("dialogue", "introspection", "description", "long_syntax", "narration"):
            chosen.extend(_pick_spread(by_category.get(category, []), 1))
        if len(chosen) < per_book:
            remainder = [candidate for candidate in candidates if candidate not in chosen]
            chosen.extend(_pick_spread(remainder, per_book - len(chosen)))
        excerpts.extend(chosen[:per_book])
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        for excerpt in excerpts:
            handle.write(json.dumps(excerpt.to_dict(), ensure_ascii=False) + "\n")
    return excerpts


def load_corpus(path: str) -> List[Excerpt]:
    allowed = {field.name for field in fields(Excerpt)}
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                data = json.loads(line)
                data = {key: value for key, value in data.items() if key in allowed}
                data.setdefault("chapter_href", "")
                rows.append(Excerpt(**data))
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build a local literary benchmark corpus")
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--out", default="data/benchmark/literary/corpus.jsonl")
    parser.add_argument("--book", action="append", help="Title or Calibre id; repeatable")
    parser.add_argument("--chapters-per-book", type=int, default=3)
    parser.add_argument("--per-book", type=int, default=5)
    args = parser.parse_args(argv)
    excerpts = build_from_inventory(
        args.inventory,
        args.out,
        books=args.book,
        chapters_per_book=args.chapters_per_book,
        per_book=args.per_book,
    )
    print(json.dumps({"excerpts": len(excerpts), "out": os.path.abspath(args.out), "by_book": {
        book: sum(1 for e in excerpts if e.book == book) for book in sorted({e.book for e in excerpts})
    }}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
