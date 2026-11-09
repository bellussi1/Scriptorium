"""Build a bilingual EN-PTBR corpus aligned at paragraph level.

The reference side is the official Brazilian edition of the Farseer trilogy;
the source side is the English original. Alignment is monotonic and scored by
shared proper nouns/numbers plus length ratio. Only high-confidence pairs are
kept, and the corpus stays under data/benchmark (gitignored).

Usage:
    python scripts/build_aligned_corpus.py --out data/benchmark/literary/corpus_aligned_farseer.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.literary.corpus import _classify  # noqa: E402
from src.literary.epub import count_words, iter_spine_documents  # noqa: E402

CALIBRE = Path(r"C:\Users\Bellussi\Biblioteca do calibre")
WORD_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)
NAME_RE = re.compile(r"\b[A-ZÀ-Ý][a-zà-ÿ'’\-]{2,}\b")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
SKIP_NAMES = {
    "The", "A", "An", "He", "She", "It", "They", "We", "I", "But", "And",
    "Then", "When", "If", "As", "At", "In", "On", "For", "With", "His",
    "Her", "Their", "This", "That", "These", "Those", "There", "What",
    "Who", "Why", "How", "Where", "Not", "No", "Yes", "Chapter", "Part",
    "Book", "Prologue", "Epilogue", "One", "Two", "Three", "Four", "Five",
    "Six", "Seven", "Eight", "Nine", "Ten", "Mr", "Mrs", "Miss", "Sir",
    "God", "Lord", "Lady", "King", "Queen", "Prince", "Princess",
}

BOOKS = [
    {
        "slug": "assassins-apprentice",
        "title": "Assassin's Apprentice",
        "author": "Robin Hobb",
        "en": CALIBRE / "Robin Hobb/Assassin's Apprentice (336)/Assassin's Apprentice - Robin Hobb.epub",
        "pt": CALIBRE / "Robin Hobb/O Aprendiz de Assassino (94)/O Aprendiz de Assassino - Robin Hobb.epub",
    },
    {
        "slug": "royal-assassin",
        "title": "Royal Assassin",
        "author": "Robin Hobb",
        "en": CALIBRE / "Robin Hobb/Royal Assassin (329)/Royal Assassin - Robin Hobb.epub",
        "pt": CALIBRE / "Robin Hobb/O Assassino do Rei (92)/O Assassino do Rei - Robin Hobb.epub",
    },
    {
        "slug": "assassins-quest",
        "title": "Assassin's Quest",
        "author": "Robin Hobb",
        "en": CALIBRE / "Robin Hobb/Assassin's Quest (338)/Assassin's Quest - Robin Hobb.epub",
        "pt": CALIBRE / "Robin Hobb/A Furia do Assassino (71)/A Furia do Assassino - Robin Hobb.epub",
    },
]


def _paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _names(text: str) -> set:
    names = {match.group(0).casefold() for match in NAME_RE.finditer(text)}
    names |= {match.group(0) for match in NUMBER_RE.finditer(text)}
    return {name for name in names if name not in {value.casefold() for value in SKIP_NAMES}}


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


def _align_chapter(en_doc: Dict[str, Any], pt_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    en_paras = [p for p in _paragraphs(en_doc["text"]) if 60 <= count_words(p) <= 260]
    pt_paras = [p for p in _paragraphs(pt_doc["text"]) if 40 <= count_words(p) <= 320]
    if not en_paras or not pt_paras:
        return []
    pairs = []
    pt_count = len(pt_paras)
    en_count = len(en_paras)
    for en_index, en_text in enumerate(en_paras):
        en_text = en_text.strip()
        if not en_text or not re.match(r"^[A-ZÀ-Ý“\"'—–-]", en_text):
            continue
        if en_text[-1] not in ".!?”\"…—:;":
            continue
        en_names = _names(en_text)
        if not en_names:
            continue
        expected = round(en_index * (pt_count - 1) / max(1, en_count - 1))
        window = range(max(0, expected - 4), min(pt_count, expected + 5))
        best = None
        for pt_index in window:
            pt_text = pt_paras[pt_index]
            pt_names = _names(pt_text)
            shared = en_names & pt_names
            ratio = count_words(pt_text) / max(1, count_words(en_text))
            if ratio < 0.55 or ratio > 1.7:
                continue
            position_penalty = abs(pt_index - expected) * 0.08
            score = len(shared) * 2.0 - abs(ratio - 1.1) - position_penalty
            if best is None or score > best["score"]:
                best = {
                    "score": score,
                    "pt_index": pt_index,
                    "shared": sorted(shared),
                    "ratio": round(ratio, 3),
                    "pt_text": pt_text,
                }
        if best is None or not best["shared"] or best["score"] < 1.2:
            continue
        pairs.append({
            "en_text": en_text,
            "pt_text": best["pt_text"],
            "shared": best["shared"],
            "ratio": best["ratio"],
            "score": round(best["score"], 3),
            "en_paragraph": en_index,
            "pt_paragraph": best["pt_index"],
            "en_href": en_doc.get("href", ""),
            "pt_href": pt_doc.get("href", ""),
        })
    return pairs


def _select(pairs: List[Dict[str, Any]], per_book: int) -> List[Dict[str, Any]]:
    # Keep the corpus balanced: up to two high-confidence pairs per category,
    # then fill the remaining slots by alignment score.
    ordered = sorted(pairs, key=lambda item: (item["score"], len(item["shared"])), reverse=True)
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for item in ordered:
        by_category.setdefault(_classify(item["en_text"]), []).append(item)
    chosen: List[Dict[str, Any]] = []
    chosen_keys = set()
    for category in ("dialogue", "description", "long_syntax", "introspection", "narration"):
        for item in by_category.get(category, [])[:2]:
            key = (item["en_text"], item["pt_paragraph"])
            if key in chosen_keys:
                continue
            chosen_keys.add(key)
            chosen.append({**item, "category": category})
            if len(chosen) >= per_book:
                return chosen[:per_book]
    for item in ordered:
        key = (item["en_text"], item["pt_paragraph"])
        if key in chosen_keys:
            continue
        chosen_keys.add(key)
        chosen.append({**item, "category": _classify(item["en_text"])})
        if len(chosen) >= per_book:
            break
    return chosen[:per_book]


def build(out_path: Path, per_book: int) -> List[Dict[str, Any]]:
    excerpts = []
    for book in BOOKS:
        if not book["en"].exists() or not book["pt"].exists():
            print("missing", book["slug"])
            continue
        en_docs = _content_docs(book["en"])
        pt_docs = _content_docs(book["pt"])
        print(book["slug"], "en docs", len(en_docs), "pt docs", len(pt_docs))
        chapter_pairs = []
        for en_doc, pt_doc in zip(en_docs, pt_docs):
            chapter_pairs.extend(_align_chapter(en_doc, pt_doc))
        selected = _select(chapter_pairs, per_book)
        for index, item in enumerate(selected):
            excerpt = {
                "id": f"{book['slug']}-{index:02d}",
                "book": book["title"],
                "author": book["author"],
                "chapter_href": item.get("en_href", ""),
                "category": item["category"],
                "text": item["en_text"],
                "source_language": "en",
                "reference_pt": item["pt_text"],
                "notes": (
                    f"aligned paragraph {item['en_paragraph']}->{item['pt_paragraph']}; "
                    f"shared={','.join(item['shared'][:6])}; ratio={item['ratio']}; "
                    f"score={item['score']}"
                ),
            }
            excerpts.append(excerpt)
        print(book["slug"], "selected", len(selected))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in excerpts) + "\n",
        encoding="utf-8",
    )
    print("wrote", out_path, len(excerpts))
    return excerpts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/benchmark/literary/corpus_aligned_farseer.jsonl")
    parser.add_argument("--per-book", type=int, default=10)
    parser.add_argument("--preview", type=int, default=0, help="print N aligned pairs for review")
    args = parser.parse_args()
    excerpts = build(Path(args.out), args.per_book)
    if args.preview:
        for item in excerpts[: args.preview]:
            print("=" * 100)
            print(item["book"], item["category"], item["notes"])
            print("EN:", item["text"][:700])
            print("PT:", item["reference_pt"][:700])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
