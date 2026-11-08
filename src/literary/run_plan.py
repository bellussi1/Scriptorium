"""Resolve everything a queue book needs for a reproducible run.

The queue stores the model/provider, source path and editorial scopes. This
module turns that row into a plan a runner can execute: which model to call,
which glossary and style apply, and which post-processing gates are enabled.
It never launches a translation by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .continuity import ContinuityTracker
from .resources import (
    CompiledResources,
    assemble_style,
    compile_for_book,
    load_tree,
    slugify,
)


@dataclass(frozen=True)
class BookScopes:
    author: str
    universe: str
    subseries: str = ""
    book: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "author": self.author,
            "universe": self.universe,
            "subseries": self.subseries,
            "book": self.book,
        }


_SERIES_TO_SUBSERIES = {
    "farseer": "farseer",
    "the farseer trilogy": "farseer",
    "liveship": "liveship-traders",
    "the liveship traders": "liveship-traders",
    "tawny man": "tawny-man",
    "the tawny man trilogy": "tawny-man",
    "fitz and the fool": "fitz-and-the-fool",
    "the fitz and the fool trilogy": "fitz-and-the-fool",
    "rain wild": "rain-wild-chronicles",
    "the rain wild chronicles": "rain-wild-chronicles",
}


def infer_scopes(book: Any) -> BookScopes:
    """Infer resource-tree coordinates from a queue book row.

    Explicit ``glossary_scope``/``style_scope`` values win when they look like
    an ``author/universe[/subseries[/book]]`` path. Otherwise the known series
    names are mapped to their directory names.
    """
    explicit = str(getattr(book, "glossary_scope", "") or getattr(book, "style_scope", "") or "").strip()
    if explicit:
        normalized = explicit.replace("\\", "/").strip("/")
        if normalized.startswith("literary-resources/"):
            normalized = normalized[len("literary-resources/") :]
        # Queue rows created before the resource-tree convention may store a
        # compiled JSON/YAML path here; that is not a scope coordinate.
        if not normalized.lower().endswith((".json", ".yaml", ".yml")):
            parts = [slugify(part) for part in normalized.split("/") if part.strip()]
            if len(parts) >= 2:
                return BookScopes(
                    author=parts[0],
                    universe=parts[1],
                    subseries=parts[2] if len(parts) > 2 else "",
                    book=parts[3] if len(parts) > 3 else "",
                )

    author = slugify(str(getattr(book, "author", "") or ""))
    series = str(getattr(book, "series", "") or "").strip()
    title = slugify(str(getattr(book, "title", "") or ""))
    series_key = series.casefold()

    if "hobb" in author:
        universe = "realm-of-the-elderlings"
        subseries = _SERIES_TO_SUBSERIES.get(series_key, "")
        return BookScopes(author=author, universe=universe, subseries=subseries, book=title)

    if "ruocchio" in author:
        return BookScopes(author=author, universe="sun-eater", book=title)

    if "mcmurtry" in author:
        return BookScopes(author=author, universe="lonesome-dove", book=title)

    return BookScopes(author=author or "unknown", universe=slugify(series) or "default", book=title)


def compile_book_resources(book: Any, resources_root: str = "literary-resources") -> CompiledResources:
    scopes = infer_scopes(book)
    tree = load_tree(resources_root)
    return compile_for_book(
        tree,
        scopes.author,
        scopes.universe,
        scopes.subseries,
        scopes.book,
    )


def build_run_plan(
    book: Any,
    *,
    resources_root: str = "literary-resources",
    refine: bool = True,
    grammar: bool = True,
    best_of_n: int = 1,
    continuity: bool = True,
    previous_chapter_text: str = "",
    pov: str = "",
    continuity_notes: str = "",
) -> Dict[str, Any]:
    """Return a JSON-serializable plan for one queue book."""
    scopes = infer_scopes(book)
    compiled = compile_book_resources(book, resources_root)
    style = assemble_style(compiled.style) if compiled.style else {"translation": "", "refinement": ""}
    terms = compiled.glossary.terms
    issues = [issue.to_dict() for issue in compiled.issues]
    tracker = ContinuityTracker.from_compiled(compiled, pov=pov, notes=continuity_notes)
    if previous_chapter_text:
        tracker.update(previous_chapter_text)

    return {
        "book": {
            "id": getattr(book, "id", None),
            "calibre_id": getattr(book, "calibre_id", None),
            "title": getattr(book, "title", ""),
            "author": getattr(book, "author", ""),
            "series": getattr(book, "series", ""),
            "series_index": getattr(book, "series_index", None),
            "status": getattr(book, "status", ""),
            "word_count": getattr(book, "word_count", 0),
        },
        "source_path": getattr(book, "source_path", ""),
        "target_language": getattr(book, "target_language", "pt-BR") or "pt-BR",
        "model": getattr(book, "model", "") or "",
        "provider": getattr(book, "provider", "") or "",
        "scopes": scopes.to_dict(),
        "glossary": {
            "terms": len(terms),
            "preview": [
                {"source": term.source, "target": term.target, "category": term.category}
                for term in terms[:10]
            ],
            "forbidden_terms": sum(1 for term in terms if term.forbidden),
        },
        "style": {
            "description": str(compiled.style.get("description") or "") if compiled.style else "",
            "translation": style.get("translation", ""),
            "refinement": style.get("refinement", ""),
            "rules": len(compiled.style.get("rules") or []) if compiled.style else 0,
        },
        "continuity": {
            "characters": [character.to_dict() for character in tracker.characters],
            "pov": tracker.pov,
            "block": tracker.block() if continuity else "",
        } if continuity else {"characters": [], "pov": tracker.pov, "block": ""},
        "pipeline": {
            "refine": bool(refine),
            "grammar": bool(grammar),
            "best_of_n": max(1, int(best_of_n)),
            "continuity": bool(continuity),
        },
        "issues": issues,
    }
