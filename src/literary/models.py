"""Shared data models for the literary translation layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: Severity = Severity.WARNING
    location: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "location": self.location,
            "evidence": self.evidence,
        }


@dataclass
class BookRecord:
    calibre_id: int
    title: str
    author: str = ""
    author_sort: str = ""
    series: str = ""
    series_index: Optional[float] = None
    languages: List[str] = field(default_factory=list)
    formats: List[str] = field(default_factory=list)
    calibre_path: str = ""
    epub_path: str = ""
    pubdate: str = ""
    identifiers: Dict[str, str] = field(default_factory=dict)
    epub_title: str = ""
    epub_language: str = ""
    epub_identifier: str = ""
    word_count: int = 0
    chapter_count: int = 0
    document_count: int = 0
    toc_titles: List[str] = field(default_factory=list)
    duplicate_group: str = ""
    issues: List[str] = field(default_factory=list)

    @property
    def is_translated_to_pt(self) -> bool:
        return any(lang.lower().startswith(("pt", "por")) for lang in self.languages)

    @property
    def is_english(self) -> bool:
        return any(lang.lower().startswith(("en", "eng")) for lang in self.languages)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calibre_id": self.calibre_id,
            "title": self.title,
            "author": self.author,
            "author_sort": self.author_sort,
            "series": self.series,
            "series_index": self.series_index,
            "languages": self.languages,
            "formats": self.formats,
            "calibre_path": self.calibre_path,
            "epub_path": self.epub_path,
            "pubdate": self.pubdate,
            "identifiers": self.identifiers,
            "epub_title": self.epub_title,
            "epub_language": self.epub_language,
            "epub_identifier": self.epub_identifier,
            "word_count": self.word_count,
            "chapter_count": self.chapter_count,
            "document_count": self.document_count,
            "toc_titles": self.toc_titles,
            "duplicate_group": self.duplicate_group,
            "issues": self.issues,
        }


@dataclass
class SeriesBook:
    slug: str
    title: str
    order: float
    kind: str = "novel"  # novel | novella | omnibus | collection
    pt_title: str = ""
    status: str = "planned"  # source | translated | planned | optional
    notes: str = ""


@dataclass
class SeriesInfo:
    slug: str
    name: str
    author_slug: str
    universe_slug: str
    books: List[SeriesBook] = field(default_factory=list)
    notes: str = ""

    def order_of(self, book_slug: str) -> Optional[float]:
        for book in self.books:
            if book.slug == book_slug:
                return book.order
        return None


@dataclass
class Term:
    source: str
    target: str = ""
    category: str = "other"
    scope: str = "series"
    policy: str = "translate"  # translate | keep | adapt | transliterate | contextual
    aliases: List[str] = field(default_factory=list)
    alias_targets: Dict[str, str] = field(default_factory=dict)
    # Derived forms the audit accepts for a target, keyed by that target:
    # {"Legião": ["legionário", "legionários"]}. Audit-side only.
    accepted_targets: Dict[str, List[str]] = field(default_factory=dict)
    forbidden: List[str] = field(default_factory=list)
    gender: str = ""
    number: str = ""
    notes: str = ""
    source_reference: str = ""
    confidence: str = "provisional"  # confirmed | reviewed | provisional
    first_appearance: str = ""
    approved: bool = False
    origin: str = ""

    def effective_target(self) -> str:
        if self.policy == "keep" and not self.target:
            return self.source
        return self.target

    def source_forms(self) -> List[str]:
        forms = [self.source, *self.aliases]
        seen = set()
        result = []
        for form in forms:
            clean = form.strip()
            if clean and clean.casefold() not in seen:
                seen.add(clean.casefold())
                result.append(clean)
        return result

    def target_for_form(self, form: str) -> str:
        """Target for a specific surface form.

        Short forms often take a different rendering from the full name
        ("FitzChivalry Farseer" vs "Fitz"). ``alias_targets`` records that
        explicitly; otherwise the canonical target is used.
        """
        for key, value in self.alias_targets.items():
            if key.strip().casefold() == (form or "").strip().casefold():
                return (value or "").strip() or self.effective_target()
        return self.effective_target()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.effective_target(),
            "category": self.category,
            "scope": self.scope,
            "policy": self.policy,
            "aliases": self.aliases,
            "alias_targets": self.alias_targets,
            "accepted_targets": self.accepted_targets,
            "forbidden": self.forbidden,
            "gender": self.gender,
            "number": self.number,
            "notes": self.notes,
            "source_reference": self.source_reference,
            "confidence": self.confidence,
            "first_appearance": self.first_appearance,
            "approved": self.approved,
            "origin": self.origin,
        }


@dataclass
class GlossaryBundle:
    terms: List[Term] = field(default_factory=list)
    version: int = 1
    source_language: str = "en"
    target_language: str = "pt-BR"
    issues: List[ValidationIssue] = field(default_factory=list)

    def term_map(self) -> Dict[str, Term]:
        return {term.source: term for term in self.terms}


@dataclass
class CompiledResources:
    glossary: GlossaryBundle
    style: Dict[str, Any] = field(default_factory=dict)
    series: Optional[SeriesInfo] = None
    book: Optional[SeriesBook] = None
    issues: List[ValidationIssue] = field(default_factory=list)


@dataclass
class QueueBook:
    id: int
    calibre_id: int
    title: str
    author: str
    series: str
    series_index: Optional[float]
    source_path: str
    source_language: str
    target_language: str
    word_count: int
    status: str
    priority: int
    glossary_scope: str
    style_scope: str
    model: str
    provider: str
    estimated_cost: float
    actual_cost: float
    source_hash: str
    config_hash: str
    created_at: str
    updated_at: str
    reviewed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class QueueChapter:
    job_id: int
    chapter_index: int
    href: str
    title: str
    status: str
    source_hash: str
    translated_hash: str
    tokens_in: int
    tokens_out: int
    cost: float
    validation_json: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class CostEstimate:
    model: str
    provider: str
    source_words: int
    input_tokens: int
    output_tokens: int
    input_cost: float
    output_cost: float
    total_cost: float
    currency: str = "USD"
    passes: int = 1
    retry_rate: float = 0.0
    assumptions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "source_words": self.source_words,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "input_cost": round(self.input_cost, 4),
            "output_cost": round(self.output_cost, 4),
            "total_cost": round(self.total_cost, 4),
            "currency": self.currency,
            "passes": self.passes,
            "retry_rate": self.retry_rate,
            "assumptions": self.assumptions,
        }
