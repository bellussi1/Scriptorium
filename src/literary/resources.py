"""Hierarchical editorial resources: glossary, worldbuilding and style.

Layout (all paths relative to ``literary-resources/``)::

    global/pt-br-conventions.yaml
    <author>/<universe>/series.yaml
    <author>/<universe>/glossary.yaml
    <author>/<universe>/style.yaml
    <author>/<universe>/<subseries>/style.yaml
    <author>/<universe>/<subseries>/glossary.yaml
    <author>/<universe>/<subseries>/<book>/glossary.yaml
    <author>/<universe>/<subseries>/<book>/style.yaml

Precedence is global < author < universe < subseries < book. A higher scope
overrides a glossary target or a style field; aliases and forbidden renderings
are merged, never silently dropped.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from .models import (
    CompiledResources,
    GlossaryBundle,
    SeriesBook,
    SeriesInfo,
    Severity,
    Term,
    ValidationIssue,
)

ALLOWED_CATEGORIES = {"character", "location", "organization", "item", "title", "concept", "other"}
ALLOWED_POLICIES = {"translate", "keep", "adapt", "transliterate", "contextual"}
ALLOWED_CONFIDENCE = {"confirmed", "reviewed", "provisional"}
SCOPE_ORDER = {"global": 0, "author": 1, "universe": 2, "subseries": 3, "book": 4, "chapter": 5}


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.casefold()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


@dataclass
class ResourceFile:
    path: Path
    rel_path: str
    scope: str
    author: str = ""
    universe: str = ""
    subseries: str = ""
    book: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceTree:
    root: Path
    files: List[ResourceFile] = field(default_factory=list)
    issues: List[ValidationIssue] = field(default_factory=list)

    def files_for(self, author: str, universe: str, subseries: str = "", book: str = "") -> List[ResourceFile]:
        result = []
        for item in self.files:
            if item.author and item.author != author:
                continue
            if item.universe and item.universe != universe:
                continue
            if item.subseries and item.subseries != subseries:
                continue
            if item.book and item.book != book:
                continue
            result.append(item)
        result.sort(key=lambda item: SCOPE_ORDER.get(item.scope, 0))
        return result


def _scope_from_parts(parts: List[str]) -> Tuple[str, str, str, str, str]:
    """Infer scope from the directory path, never from the file stem.

    ``parts`` are the directories between the resource root and the YAML file:
    ``global``; ``<author>``; ``<author>/<universe>``;
    ``<author>/<universe>/<subseries>``; ``<author>/<universe>/<subseries>/<book>``.
    """
    if not parts or parts[0] == "global":
        return "global", "", "", "", ""
    if len(parts) == 1:
        return "author", parts[0], "", "", ""
    if len(parts) == 2:
        return "universe", parts[0], parts[1], "", ""
    if len(parts) == 3:
        return "subseries", parts[0], parts[1], parts[2], ""
    return "book", parts[0], parts[1], parts[2], parts[3]


def load_tree(root: str | Path) -> ResourceTree:
    root_path = Path(root).resolve()
    tree = ResourceTree(root=root_path)
    if not root_path.exists():
        tree.issues.append(ValidationIssue("resources.missing", f"Resource root not found: {root_path}", Severity.ERROR))
        return tree
    for path in sorted(root_path.rglob("*.yaml")):
        if not path.is_file():
            continue
        rel = path.relative_to(root_path).as_posix()
        # Scope is a property of the directory tree. A file's stem
        # ("glossary", "style", ...) must not be mistaken for a subseries.
        dir_parts = list(path.relative_to(root_path).parent.parts)
        scope, author, universe, subseries, book = _scope_from_parts(dir_parts)
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            if not isinstance(data, dict):
                raise ValueError("top-level YAML value must be a mapping")
        except Exception as exc:
            tree.issues.append(ValidationIssue("resources.yaml", f"{rel}: {exc}", Severity.ERROR, rel))
            continue
        tree.files.append(
            ResourceFile(
                path=path,
                rel_path=rel,
                scope=scope,
                author=author,
                universe=universe,
                subseries=subseries,
                book=book,
                data=data,
            )
        )
    return tree


def _parse_term(raw: Dict[str, Any], origin: str, scope: str) -> Tuple[Optional[Term], List[ValidationIssue]]:
    issues: List[ValidationIssue] = []
    if not isinstance(raw, dict):
        return None, [ValidationIssue("glossary.term_type", f"Term in {origin} is not a mapping", Severity.ERROR, origin)]
    source = str(raw.get("source") or raw.get("source_term") or "").strip()
    target = str(raw.get("target") or raw.get("translated_term") or "").strip()
    policy = str(raw.get("policy") or "translate").strip().lower()
    category = str(raw.get("category") or "other").strip().lower()
    confidence = str(raw.get("confidence") or "provisional").strip().lower()
    if not source:
        issues.append(ValidationIssue("glossary.source_missing", f"Term without source in {origin}", Severity.ERROR, origin))
        return None, issues
    if policy not in ALLOWED_POLICIES:
        issues.append(ValidationIssue("glossary.policy", f"Unknown policy '{policy}' for '{source}'", Severity.WARNING, origin))
        policy = "translate"
    if category not in ALLOWED_CATEGORIES:
        issues.append(ValidationIssue("glossary.category", f"Unknown category '{category}' for '{source}'", Severity.WARNING, origin))
        category = "other"
    if confidence not in ALLOWED_CONFIDENCE:
        issues.append(ValidationIssue("glossary.confidence", f"Unknown confidence '{confidence}' for '{source}'", Severity.WARNING, origin))
        confidence = "provisional"
    if policy == "keep" and not target:
        target = source
    if not target:
        issues.append(ValidationIssue("glossary.target_missing", f"Term '{source}' has no target", Severity.ERROR, origin))
    aliases = raw.get("aliases") or []
    forbidden = raw.get("forbidden_translations") or raw.get("forbidden") or []
    alias_targets_raw = raw.get("alias_targets") or {}
    if isinstance(aliases, str):
        aliases = [aliases]
    if isinstance(forbidden, str):
        forbidden = [forbidden]
    if not isinstance(alias_targets_raw, dict):
        alias_targets_raw = {}
    alias_targets = {
        str(key).strip(): str(value).strip()
        for key, value in alias_targets_raw.items()
        if str(key).strip() and str(value).strip()
    }
    aliases_clean = [str(a).strip() for a in aliases if str(a).strip()]
    for alias in alias_targets:
        if alias.casefold() not in {a.casefold() for a in aliases_clean}:
            aliases_clean.append(alias)
    return (
        Term(
            source=source,
            target=target,
            category=category,
            scope=scope,
            policy=policy,
            aliases=aliases_clean,
            alias_targets=alias_targets,
            forbidden=[str(a).strip() for a in forbidden if str(a).strip()],
            gender=str(raw.get("gender") or "").strip().lower(),
            number=str(raw.get("number") or "").strip().lower(),
            notes=str(raw.get("notes") or "").strip(),
            source_reference=str(raw.get("source_reference") or "").strip(),
            confidence=confidence,
            first_appearance=str(raw.get("first_appearance") or "").strip(),
            approved=bool(raw.get("approved", False)),
            origin=origin,
        ),
        issues,
    )


def _terms_from_file(item: ResourceFile) -> Tuple[List[Term], List[ValidationIssue]]:
    raw_terms = item.data.get("terms")
    if raw_terms is None:
        return [], []
    if not isinstance(raw_terms, list):
        return [], [ValidationIssue("glossary.terms_type", f"'terms' in {item.rel_path} must be a list", Severity.ERROR, item.rel_path)]
    terms: List[Term] = []
    issues: List[ValidationIssue] = []
    for raw in raw_terms:
        term, term_issues = _parse_term(raw, item.rel_path, item.scope)
        issues.extend(term_issues)
        if term is not None:
            terms.append(term)
    return terms, issues


def _series_from_file(item: ResourceFile) -> Optional[SeriesInfo]:
    if item.scope != "universe" or item.path.name not in {"series.yaml", "series.yml"}:
        return None
    data = item.data
    books: List[SeriesBook] = []
    for raw in data.get("books") or []:
        if not isinstance(raw, dict):
            continue
        slug = str(raw.get("slug") or slugify(raw.get("title") or ""))
        if not slug:
            continue
        books.append(
            SeriesBook(
                slug=slug,
                title=str(raw.get("title") or ""),
                order=float(raw.get("order") or 0),
                kind=str(raw.get("kind") or "novel"),
                pt_title=str(raw.get("pt_title") or ""),
                status=str(raw.get("status") or "planned"),
                notes=str(raw.get("notes") or ""),
            )
        )
    return SeriesInfo(
        slug=str(data.get("slug") or item.universe),
        name=str(data.get("name") or item.universe),
        author_slug=item.author,
        universe_slug=item.universe,
        books=books,
        notes=str(data.get("notes") or ""),
    )


def validate_tree(tree: ResourceTree) -> List[ValidationIssue]:
    issues = list(tree.issues)
    known_books: Dict[str, SeriesInfo] = {}
    for item in tree.files:
        series = _series_from_file(item)
        if series:
            known_books[series.slug] = series
    for item in tree.files:
        if item.data.get("terms") is not None:
            _, term_issues = _terms_from_file(item)
            issues.extend(term_issues)
        if item.path.name in {"style.yaml", "style.yml"}:
            if not any(key in item.data for key in ("translation", "refinement", "rules")):
                issues.append(ValidationIssue("style.empty", f"{item.rel_path} has no translation, refinement or rules", Severity.WARNING, item.rel_path))
    # first_appearance must point at a known book slug.
    all_slugs = {book.slug for series in known_books.values() for book in series.books}
    for item in tree.files:
        if item.data.get("terms") is None:
            continue
        terms, _ = _terms_from_file(item)
        for term in terms:
            if term.first_appearance and all_slugs and term.first_appearance not in all_slugs:
                issues.append(
                    ValidationIssue(
                        "glossary.first_appearance",
                        f"'{term.source}' references unknown book '{term.first_appearance}'",
                        Severity.WARNING,
                        item.rel_path,
                    )
                )
    return issues


def _merge_terms(base: List[Term], overlay: List[Term]) -> List[Term]:
    by_key: Dict[str, Term] = {normalize_key(term.source): term for term in base}
    order: List[str] = [normalize_key(term.source) for term in base]
    for term in overlay:
        key = normalize_key(term.source)
        if key not in by_key:
            by_key[key] = term
            order.append(key)
            continue
        current = by_key[key]
        current.target = term.target or current.target
        current.category = term.category or current.category
        current.scope = term.scope
        current.policy = term.policy or current.policy
        current.gender = term.gender or current.gender
        current.number = term.number or current.number
        current.notes = term.notes or current.notes
        current.source_reference = term.source_reference or current.source_reference
        current.confidence = term.confidence or current.confidence
        current.first_appearance = term.first_appearance or current.first_appearance
        current.approved = term.approved or current.approved
        current.origin = term.origin
        current.aliases = list(dict.fromkeys([*current.aliases, *term.aliases]))
        current.alias_targets = {**current.alias_targets, **term.alias_targets}
        current.forbidden = list(dict.fromkeys([*current.forbidden, *term.forbidden]))
    return [by_key[key] for key in order]


def _merge_style(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key == "rules" and isinstance(value, list):
            current = list(merged.get("rules") or [])
            by_dimension = {str(rule.get("dimension") or ""): i for i, rule in enumerate(current) if isinstance(rule, dict)}
            for rule in value:
                if not isinstance(rule, dict):
                    continue
                dimension = str(rule.get("dimension") or "")
                if dimension in by_dimension:
                    current[by_dimension[dimension]] = rule
                else:
                    current.append(rule)
            merged["rules"] = current
        elif key in {"translation", "refinement"} and value:
            merged[key] = value
        else:
            merged[key] = value
    return merged


def compile_for_book(
    tree: ResourceTree,
    author: str,
    universe: str,
    subseries: str = "",
    book: str = "",
    book_order: Optional[float] = None,
) -> CompiledResources:
    author = slugify(author)
    universe = slugify(universe)
    subseries = slugify(subseries) if subseries else ""
    book = slugify(book) if book else ""

    files = tree.files_for(author, universe, subseries, book)
    series: Optional[SeriesInfo] = None
    for item in files:
        candidate = _series_from_file(item)
        if candidate:
            series = candidate
            break
    current_book: Optional[SeriesBook] = None
    if series and book:
        current_book = next((b for b in series.books if b.slug == book), None)
    if book_order is None and current_book is not None:
        book_order = current_book.order

    terms: List[Term] = []
    style: Dict[str, Any] = {}
    issues: List[ValidationIssue] = []
    for item in files:
        if item.data.get("terms") is not None:
            file_terms, file_issues = _terms_from_file(item)
            terms = _merge_terms(terms, file_terms)
            issues.extend(file_issues)
        if item.path.name in {"style.yaml", "style.yml"}:
            style = _merge_style(style, item.data)
        issues.extend(tree.issues)

    if series and book_order is not None:
        available = []
        for term in terms:
            if not term.first_appearance:
                available.append(term)
                continue
            first = next((b.order for b in series.books if b.slug == term.first_appearance), None)
            if first is None:
                issues.append(
                    ValidationIssue(
                        "glossary.first_appearance",
                        f"'{term.source}' references unknown book '{term.first_appearance}'; keeping it",
                        Severity.WARNING,
                        term.origin,
                    )
                )
                available.append(term)
            elif first <= book_order:
                available.append(term)
        terms = available

    return CompiledResources(
        glossary=GlossaryBundle(terms=terms),
        style=style,
        series=series,
        book=current_book,
        issues=issues,
    )


def _target_groups(term: Term) -> List[Tuple[str, List[str]]]:
    """Group surface forms by the target they require.

    ``FitzChivalry Farseer`` and ``Fitz`` are the same entity but not the same
    Portuguese rendering. The upstream filter keys on a source string and a
    single target, so groups with different targets must become separate
    entries.
    """
    groups: Dict[str, Tuple[str, List[str]]] = {}
    order: List[str] = []
    for form in term.source_forms():
        target = term.target_for_form(form)
        if not target:
            continue
        key = target.casefold()
        if key not in groups:
            groups[key] = (target, [])
            order.append(key)
        groups[key][1].append(form)
    return [(groups[key][0], groups[key][1]) for key in order]


def glossary_to_prompt_dicts(compiled: CompiledResources) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]], Dict[str, List[str]]]:
    """Return (terms, metadata, forbidden) in the shape the upstream prompt path consumes."""
    terms: Dict[str, str] = {}
    metadata: Dict[str, Dict[str, str]] = {}
    forbidden: Dict[str, List[str]] = {}
    for term in compiled.glossary.terms:
        for target, forms in _target_groups(term):
            source = "|".join(forms)
            if not source or not target:
                continue
            terms[source] = target
            meta: Dict[str, str] = {}
            if term.category:
                meta["category"] = term.category
            if term.gender:
                meta["gender"] = term.gender
            if term.forbidden:
                # The upstream injector consumes a string; keep the JSON form a
                # list. "|" is already the glossary's alternative separator.
                meta["forbidden"] = "|".join(term.forbidden)
            if meta:
                metadata[source] = meta
            if term.forbidden:
                forbidden[source] = list(term.forbidden)
    return terms, metadata, forbidden


def write_glossary_json(compiled: CompiledResources, output_path: str, name: str = "") -> str:
    entries = []
    for term in compiled.glossary.terms:
        for target, forms in _target_groups(term):
            entries.append(
                {
                    "source": "|".join(forms),
                    "target": target,
                    "category": term.category,
                    "gender": term.gender,
                    "forbidden": term.forbidden,
                    "policy": term.policy,
                    "confidence": term.confidence,
                    "source_reference": term.source_reference,
                }
            )
    payload = {
        "name": name or (compiled.series.name if compiled.series else "literary"),
        "source_language": compiled.glossary.source_language,
        "target_language": compiled.glossary.target_language,
        "terms": entries,
    }
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    temp = output_path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp, output_path)
    return output_path


def _fallback_assemble(mode: str, rules: List[Dict[str, Any]], context: str) -> Dict[str, str]:
    lines = []
    if context:
        lines.extend(["## Setting", "", context, ""])
    lines.extend(["## Style", ""])
    for rule in rules:
        instruction = str(rule.get("instruction") or "").strip()
        if instruction:
            lines.append(f"- {instruction}")
    block = "\n".join(lines) + "\n"
    preamble = (
        "Match the following writing style in the translation. These rules describe how the text must read; "
        "they never authorize adding, removing, or altering content.\n\n"
    )
    return {"translation": preamble + block, "refinement": preamble + block}


def assemble_style(style: Dict[str, Any]) -> Dict[str, str]:
    """Return translation/refinement prose for a style profile."""
    translation = str(style.get("translation") or "").strip()
    refinement = str(style.get("refinement") or "").strip()
    if translation and refinement:
        return {"translation": translation, "refinement": refinement}
    rules = style.get("rules") or []
    context = str(style.get("context") or "")
    mode = str(style.get("mode") or "source")
    try:
        from src.core.style.assembler import assemble_instructions

        assembled = assemble_instructions(mode, rules, context)
        translation = translation or assembled.get("translation", "")
        refinement = refinement or assembled.get("refinement", "")
    except Exception:
        fallback = _fallback_assemble(mode, rules, context)
        translation = translation or fallback["translation"]
        refinement = refinement or fallback["refinement"]
    return {"translation": translation, "refinement": refinement}


def write_style_preset(compiled: CompiledResources, output_path: str, description: str = "") -> str:
    assembled = assemble_style(compiled.style)
    payload = {
        "description": description or str(compiled.style.get("description") or ""),
        "mode": str(compiled.style.get("mode") or "source"),
        "context": str(compiled.style.get("context") or ""),
        "rules": compiled.style.get("rules") or [],
        "translation": assembled["translation"],
        "refinement": assembled["refinement"],
    }
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    temp = output_path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
    os.replace(temp, output_path)
    return output_path
