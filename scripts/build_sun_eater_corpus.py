"""Build the Sun Eater evaluation corpus from the official PT edition.

Sun Eater is the first priority series. Book 1, *Empire of Silence*, has an
official Brazilian edition (Calibre 436) and a matching English source, so it
can support the same reference-based metrics as Farseer: chrF, term/name
probes, long chapters and blind A/B.

Outputs (all under data/benchmark/literary, gitignored):
    eval_sun_eater_dev.jsonl
    eval_sun_eater_test.jsonl
    probes_names_sun_eater.jsonl
    probes_terms_sun_eater.jsonl
    probes_run_sun_eater.jsonl
    long_chapters_sun_eater.jsonl
    eval_sun_eater_manifest.json

Run:
    python scripts/build_sun_eater_corpus.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.build_eval_corpus as base  # noqa: E402
from src.literary.epub import count_words, iter_spine_documents  # noqa: E402
from src.literary.resources import compile_for_book, load_tree  # noqa: E402

CALIBRE = Path(r"C:\Users\Bellussi\Biblioteca do calibre")
OUT = ROOT / "data" / "benchmark" / "literary"
SUN_RESOURCES = ROOT / "literary-resources" / "christopher-ruocchio" / "sun-eater"


class SimpleTerm:
    """Minimal term adapter for the split Sun Eater resource files."""

    def __init__(self, payload: Dict[str, Any]):
        self.source = str(payload.get("source") or "")
        self.target = str(payload.get("target") or "")
        self.category = str(payload.get("category") or "other")
        self.aliases = [str(item) for item in payload.get("aliases") or [] if str(item).strip()]
        self.alias_targets = {
            str(key): str(value) for key, value in (payload.get("alias_targets") or {}).items()
        }
        self.forbidden = [str(item) for item in payload.get("forbidden") or [] if str(item).strip()]

    def source_forms(self) -> List[str]:
        return [self.source] + self.aliases if self.source else list(self.aliases)

    def target_for_form(self, form: str) -> str:
        return self.alias_targets.get(form, self.target)


def load_sun_terms() -> List[SimpleTerm]:
    terms: List[SimpleTerm] = []
    seen = set()
    for filename in ("glossary.yaml", "characters.yaml", "worldbuilding.yaml"):
        path = SUN_RESOURCES / filename
        if not path.exists():
            continue
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in payload.get("terms") or []:
            if not isinstance(item, dict):
                continue
            term = SimpleTerm(item)
            key = (term.source, term.category)
            if not term.source or key in seen:
                continue
            seen.add(key)
            terms.append(term)
    return terms

SUN_BOOK = {
    "slug": "empire-of-silence",
    "title": "Empire of Silence",
    "author": "Christopher Ruocchio",
    "order": 1,
    "en": Path(r"C:\Users\Bellussi\Downloads\Livros e leitura\Sun Eater\Empire of Silence - Christopher Ruocchio.epub"),
    "pt": CALIBRE / "Christopher Ruocchio/Imperio do Silencio (436)/Imperio do Silencio - Christopher Ruocchio.epub",
}

CHAPTER_RE = re.compile(r"(?:Chapter|Capítulo)\s+(\d+)", re.IGNORECASE)


def _chapter_number(title: str) -> int | None:
    match = CHAPTER_RE.search(title or "")
    return int(match.group(1)) if match else None


def _docs_by_chapter(path: Path) -> Dict[int, Dict[str, Any]]:
    docs = base._content_docs(path)
    toc = base._toc_map(path)
    by_number: Dict[int, Dict[str, Any]] = {}
    for doc in docs:
        href = str(doc.get("href") or "").lower()
        title = toc.get(href, "")
        number = _chapter_number(title)
        if number is not None and number not in by_number:
            by_number[number] = doc
    return by_number


def build_candidates() -> Tuple[List[base.Candidate], Dict[str, Any]]:
    if not SUN_BOOK["en"].exists():
        raise FileNotFoundError(SUN_BOOK["en"])
    if not SUN_BOOK["pt"].exists():
        raise FileNotFoundError(SUN_BOOK["pt"])
    tree = load_tree(str(base.RESOURCES))
    compiled = compile_for_book(tree, "christopher-ruocchio", "sun-eater", "", "Empire of Silence")
    terms = load_sun_terms()
    patterns = base._term_patterns(terms)
    en_docs = _docs_by_chapter(SUN_BOOK["en"])
    pt_docs = _docs_by_chapter(SUN_BOOK["pt"])
    en_toc = base._toc_map(SUN_BOOK["en"])
    pt_toc = base._toc_map(SUN_BOOK["pt"])
    common = sorted(set(en_docs) & set(pt_docs))
    candidates: List[base.Candidate] = []
    skipped: List[Tuple[int, float]] = []
    for number in common:
        en_doc = en_docs[number]
        pt_doc = pt_docs[number]
        en_words = count_words(en_doc.get("text") or "")
        pt_words = count_words(pt_doc.get("text") or "")
        ratio = pt_words / max(1, en_words)
        if ratio < 0.65 or ratio > 1.55:
            skipped.append((number, round(ratio, 2)))
            continue
        title = en_toc.get(str(en_doc.get("href") or "").lower(), "")
        if not title:
            title = pt_toc.get(str(pt_doc.get("href") or "").lower(), "")
        title = title or f"Chapter {number}"
        candidates.extend(
            base._align_chapter(en_doc, pt_doc, number - 1, title, SUN_BOOK, patterns)
        )
    diagnostics = {
        "book": SUN_BOOK["title"],
        "terms": len(terms),
        "character_terms": sum(1 for term in terms if term.category == "character"),
        "en_chapters": len(en_docs),
        "pt_chapters": len(pt_docs),
        "paired_chapters": len(common),
        "skipped_ratio": skipped,
        "candidates": len(candidates),
        "categories": dict(Counter(item.category for item in candidates)),
        "confidence": dict(Counter(item.confidence for item in candidates)),
    }
    return candidates, diagnostics


def select_sun_eater(candidates: Sequence[base.Candidate]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # The shared selector uses BOOKS for round-robin ordering; scope it to this
    # single book while building the Sun Eater split.
    original_books = base.BOOKS
    base.BOOKS = [SUN_BOOK]
    try:
        selected = base.select_corpus(candidates)
        by_category: Dict[str, List[base.Candidate]] = defaultdict(list)
        for item in selected:
            by_category[item.category].append(item)
        rows: List[Dict[str, Any]] = []
        for category_index, category in enumerate(base.CATEGORIES):
            items = by_category.get(category, [])
            if not items:
                continue
            test_count = max(2, round(len(items) / 3))
            dev_items, test_items = base._split_items(items, test_count, offset=category_index)
            for item in dev_items:
                row = item.to_dict()
                row["split"] = "dev"
                rows.append(row)
            for item in test_items:
                row = item.to_dict()
                row["split"] = "test"
                rows.append(row)
    finally:
        base.BOOKS = original_books
    diagnostics = {
        "selected": len(rows),
        "dev": sum(1 for row in rows if row["split"] == "dev"),
        "test": sum(1 for row in rows if row["split"] == "test"),
        "by_category": dict(Counter(row["category"] for row in rows)),
        "by_split_category": {
            split: dict(Counter(row["category"] for row in rows if row["split"] == split))
            for split in ("dev", "test")
        },
    }
    return rows, diagnostics


def build_probes(candidates: Sequence[base.Candidate], selected: Sequence[base.Candidate]) -> Dict[str, List[Dict[str, Any]]]:
    selected_ids = {item.id for item in selected}
    pool = [item for item in candidates if item.id not in selected_ids]
    original_books = base.BOOKS
    base.BOOKS = [SUN_BOOK]
    try:
        name_pool = [
            item
            for item in pool
            if 2 <= len(item.character_matches) <= 4
            and item.confidence == "high"
            and base._reference_coverage(item, item.character_matches) >= 0.8
        ]
        term_pool = [
            item
            for item in pool
            if len([term for term in item.term_matches if term.category != "character"]) >= 2
            and item.confidence == "high"
            and base._reference_coverage(
                item,
                [term for term in item.term_matches if term.category != "character"],
            )
            >= 0.6
        ]
        names = base._round_robin(name_pool, 25)
        name_texts = {item.text for item in names}
        term_pool = [item for item in term_pool if item.text not in name_texts]
        terms = base._round_robin(term_pool, 25)
    finally:
        base.BOOKS = original_books

    name_rows = []
    for index, item in enumerate(names, start=1):
        name_rows.append(
            base._probe_payload(
                probe_id=f"probe-name-sun-eater-{index:03d}",
                kind="name",
                series="The Sun Eater",
                book={"title": item.book, "slug": item.book_slug, "author": item.author},
                text=item.text,
                reference=item.reference_pt,
                reference_kind="official_pt",
                terms=item.character_matches,
                characters=item.character_matches,
                character_pool=item.character_pool,
                notes=f"aligned {item.book_slug} chapter {item.chapter_index}; official PT reference",
                reference_coverage=base._reference_coverage(item, item.character_matches),
            )
        )
    term_rows = []
    for index, item in enumerate(terms, start=1):
        non_character = [term for term in item.term_matches if term.category != "character"]
        term_rows.append(
            base._probe_payload(
                probe_id=f"probe-term-sun-eater-{index:03d}",
                kind="term",
                series="The Sun Eater",
                book={"title": item.book, "slug": item.book_slug, "author": item.author},
                text=item.text,
                reference=item.reference_pt,
                reference_kind="official_pt",
                terms=non_character,
                characters=item.character_matches,
                character_pool=item.character_pool,
                notes=f"aligned {item.book_slug} chapter {item.chapter_index}; official PT reference",
                reference_coverage=base._reference_coverage(item, non_character),
            )
        )
    return {"names": name_rows, "terms": term_rows}


def build_long_chapter() -> List[Dict[str, Any]]:
    en_docs = _docs_by_chapter(SUN_BOOK["en"])
    pt_docs = _docs_by_chapter(SUN_BOOK["pt"])
    en_toc = base._toc_map(SUN_BOOK["en"])
    tree = load_tree(str(base.RESOURCES))
    compiled = compile_for_book(tree, "christopher-ruocchio", "sun-eater", "", "Empire of Silence")
    terms = load_sun_terms()
    patterns = base._term_patterns(terms)
    best = None
    for number in sorted(set(en_docs) & set(pt_docs)):
        en_doc = en_docs[number]
        pt_doc = pt_docs[number]
        words = count_words(en_doc.get("text") or "")
        if not (3000 <= words <= 5500):
            continue
        ratio = count_words(pt_doc.get("text") or "") / max(1, words)
        if not (0.65 <= ratio <= 1.55):
            continue
        if best is None or words > best[0]:
            best = (words, number, en_doc, pt_doc, ratio)
    if best is None:
        return []
    words, number, en_doc, pt_doc, ratio = best
    title = en_toc.get(str(en_doc.get("href") or "").lower(), f"Chapter {number}")
    text = en_doc.get("text") or ""
    expected = [
        {"source": term.source, "target": term.target, "category": term.category}
        for term in base._match_terms(text, patterns)
    ][:40]
    return [{
        "id": f"long-sun-eater-{number:02d}",
        "kind": "long_chapter",
        "book": SUN_BOOK["title"],
        "book_slug": SUN_BOOK["slug"],
        "author": SUN_BOOK["author"],
        "chapter_index": number - 1,
        "chapter_title": title,
        "text": text,
        "reference_pt": pt_doc.get("text") or "",
        "source_language": "en",
        "target_language": "pt-BR",
        "word_count": words,
        "reference_word_count": count_words(pt_doc.get("text") or ""),
        "ratio": round(ratio, 3),
        "expected_terms": expected,
        "notes": "full chapter in the 3-5.5k word range; use the queue chunker, not a single prompt",
    }]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    candidates, build_diag = build_candidates()
    rows, split_diag = select_sun_eater(candidates)
    dev = [row for row in rows if row["split"] == "dev"]
    test = [row for row in rows if row["split"] == "test"]
    base._write_jsonl(OUT / "eval_sun_eater_dev.jsonl", dev)
    base._write_jsonl(OUT / "eval_sun_eater_test.jsonl", test)

    selected = [item for item in candidates if item.id in {row["id"] for row in rows}]
    probes = build_probes(candidates, selected)
    base._write_jsonl(OUT / "probes_names_sun_eater.jsonl", probes["names"])
    base._write_jsonl(OUT / "probes_terms_sun_eater.jsonl", probes["terms"])
    with (OUT / "probes_run_sun_eater.jsonl").open("w", encoding="utf-8") as handle:
        for path in (OUT / "probes_names_sun_eater.jsonl", OUT / "probes_terms_sun_eater.jsonl"):
            handle.write(path.read_text(encoding="utf-8"))

    long_rows = build_long_chapter()
    base._write_jsonl(OUT / "long_chapters_sun_eater.jsonl", long_rows)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "book": SUN_BOOK["title"],
        "build": build_diag,
        "split": split_diag,
        "probes": {"names": len(probes["names"]), "terms": len(probes["terms"])},
        "long_chapters": [
            {"id": row["id"], "chapter_title": row["chapter_title"], "words": row["word_count"]}
            for row in long_rows
        ],
        "files": [
            "eval_sun_eater_dev.jsonl",
            "eval_sun_eater_test.jsonl",
            "probes_names_sun_eater.jsonl",
            "probes_terms_sun_eater.jsonl",
            "probes_run_sun_eater.jsonl",
            "long_chapters_sun_eater.jsonl",
        ],
    }
    (OUT / "eval_sun_eater_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
