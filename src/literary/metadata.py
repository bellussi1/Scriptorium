"""Calibre-aligned OPF metadata, tags, title and synopsis standardization."""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..config import GENERATOR_NAME
from .epub import (
    _local_name,
    _read_container,
    _read_opf,
    read_epub,
    update_opf_metadata,
)
from .queue import QueueStore
from .validation import validate_epub_pair

SCRIPTORIUM_TAG = "Scriptorium"
LANGUAGE_TAG = "PT-BR"
SCRIPTORIUM_REPO_URL = "https://github.com/bellussi1/Scriptorium"
_SCRIPTORIUM_NOTE = (
    "Tradução para o português brasileiro realizada de forma automatizada e revisada "
    "para leitura pessoal, utilizando o modelo Gemini 3.8 Flash por meio do pipeline "
    f"Scriptorium ({SCRIPTORIUM_REPO_URL})."
)

_NOISE_TAG_KEYS = {
    "en",
    "pt-br",
    "pt-pt",
    "por",
    "eng",
    "brazilian portuguese",
    "machine translation",
    "tradução ia",
    "traducao ia",
    "scriptorium",
    "no data",
}
_BISAC_TAG_RE = re.compile(r"^[A-Z]{3}\d{6}\b")

_CURATED_DESCRIPTIONS_PTBR: Dict[str, str] = {
    "disquiet gods": (
        "<p><b>O sexto romance da série galáctica Sun Eater combina o melhor da "
        "ópera espacial e da fantasia épica, enquanto Hadrian Marlowe segue por "
        "um caminho que só pode terminar em fogo.</b></p>\n"
        "<p>O fim está próximo.</p>\n"
        "<p>Quase duzentos anos se passaram desde que Hadrian Marlowe atentou "
        "contra a pessoa do Imperador e deu as costas à guerra. Ao seu Império. "
        "Ao seu dever. À vontade e ao serviço do ser arcano conhecido apenas como "
        "os Quietos. A galáxia jaz sob o jugo de uma praga terrível e, pior "
        "ainda, os cielcin invadiram os reinos dos homens.</p>\n"
        "<p>Um mensageiro chegou a Jadd trazendo uma convocação do Imperador "
        "Sollano para o antigo herói. Uma convocação, um perdão e uma súplica. A "
        "HAPSIS, organização secreta de inteligência de primeiro contato do "
        "Império, localizou um dos terríveis Vigilantes, os seres imensos e "
        "poderosos adorados pelos cielcin pálidos.</p>\n"
        "<p>Arrancado da aposentadoria e do exílio, o velho herói — acompanhado "
        "de sua filha, Cassandra — precisará correr pela galáxia e contra o "
        "tempo para cumprir uma última e impossível tarefa:</p>\n"
        "<p>Matar um deus.</p>"
    ),
}

_FOOTER_PATTERNS = (
    re.compile(r"\s*<p>\s*<i>\s*Tradução para o português brasileiro realizada de forma automatizada.+?Scriptorium(?:\s*\([^)]+\))?\.?\s*</i>\s*</p>\s*$", re.I | re.S),
    re.compile(r"(?:\s*<br\s*/?>)+\s*<i>\s*Tradução para o português brasileiro realizada de forma automatizada.+?Scriptorium(?:\s*\([^)]+\))?\.?\s*</i>\s*$", re.I | re.S),
    re.compile(r"\s*Tradução para o português brasileiro realizada de forma automatizada.+?Scriptorium(?:\s*\([^)]+\))?\.?\s*$", re.I | re.S),
    re.compile(r"\s*<p>\s*<i>\s*Tradução em português brasileiro via Scriptorium\.?\s*</i>\s*</p>\s*$", re.I),
    re.compile(r"(?:\s*<br\s*/?>)+\s*<i>\s*Tradução em português brasileiro via Scriptorium\.?\s*</i>\s*$", re.I),
    re.compile(r"\s*Translated using Scriptorium(?:\s+https?://\S+)?\s*$", re.I),
    re.compile(r"\s*Translated using TranslateBook with LLM \(TBL\)(?:\s+https?://\S+)?\s*$", re.I),
    re.compile(r"\s*Tradução em português brasileiro via Scriptorium\.?\s*$", re.I),
    re.compile(
        r"^\s*Edição em português brasileiro de .+?\.\s*"
        r"Tradução assistida por IA;\s*revisão editorial recomendada\.?\s*$",
        re.I | re.S,
    ),
)


def author_sort(author: str) -> str:
    parts = [part for part in (author or "").strip().split() if part]
    if len(parts) <= 1:
        return " ".join(parts)
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def _clean_tag(tag: str) -> str:
    return re.sub(r"\s+", " ", (tag or "").strip())


def _is_noise_tag(tag: str) -> bool:
    cleaned = _clean_tag(tag)
    if not cleaned:
        return True
    if cleaned.casefold() in _NOISE_TAG_KEYS:
        return True
    return bool(_BISAC_TAG_RE.match(cleaned))


def normalize_tags(
    raw_tags: Iterable[str],
    *,
    include_scriptorium: bool = True,
) -> List[str]:
    """Deduplicate tags and enforce Calibre ``PT-BR`` (+ optional ``Scriptorium``)."""
    tags = [_clean_tag(tag) for tag in raw_tags if not _is_noise_tag(tag)]
    tags.append(LANGUAGE_TAG)
    if include_scriptorium:
        tags.append(SCRIPTORIUM_TAG)
    return list(dict.fromkeys(tags))


def infer_calibre_library(source_path: str = "", explicit: str = "") -> str:
    """Resolve the Calibre library directory from an explicit flag, env, or EPUB path."""
    if explicit:
        return explicit
    env_path = os.environ.get("CALIBRE_LIBRARY_PATH", "").strip()
    if env_path:
        return env_path
    if source_path:
        try:
            resolved = Path(source_path).resolve()
            if len(resolved.parents) >= 3:
                candidate = resolved.parents[2]
                if (candidate / "metadata.db").is_file():
                    return str(candidate)
        except OSError:
            pass
    return ""


def read_calibre_tags(calibre_library: str, calibre_id: Optional[int]) -> List[str]:
    """Read normalized Calibre tags for ``calibre_id`` via a read-only connection."""
    if not calibre_library or not calibre_id or int(calibre_id) <= 0:
        return []
    db_path = Path(calibre_library) / "metadata.db"
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            """
            SELECT t.name
            FROM books_tags_link btl
            JOIN tags t ON t.id = btl.tag
            WHERE btl.book = ?
            ORDER BY btl.id, t.id
            """,
            (int(calibre_id),),
        ).fetchall()
        return [str(row["name"] or "").strip() for row in rows if str(row["name"] or "").strip()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _fallback_genre_tags(book: Any) -> List[str]:
    author = str(getattr(book, "author", "") or "").casefold()
    series = str(getattr(book, "series", "") or "").strip()
    series_cf = series.casefold()
    title_cf = str(getattr(book, "title", "") or "").casefold()

    if "hobb" in author:
        return ["Realm of the Elderlings", "Fiction", "Speculative Fiction", "Fantasy", "Epic Fantasy", "High Fantasy"]
    if "ruocchio" in author or "sun eater" in series_cf:
        return ["Fiction", "Speculative Fiction", "Science Fiction", "Space Opera", "Science Fantasy"]
    if "mcmurtry" in author or "lonesome dove" in title_cf:
        return ["Fiction", "Classic", "Historical Fiction", "Western"]
    if "erikson" in author or "malazan" in series_cf:
        return ["Fiction", "Speculative Fiction", "Fantasy", "Epic Fantasy", "High Fantasy", "Military Fantasy"]
    if "gwynne" in author:
        return ["Fiction", "Speculative Fiction", "Fantasy", "Epic Fantasy", "High Fantasy"]
    if "abercrombie" in author:
        subgenre = "Epic Fantasy" if series else "Dark Fantasy"
        return ["Grimdark", "Fiction", "Speculative Fiction", "Fantasy", subgenre]
    if "islington" in author:
        return ["Fiction", "Speculative Fiction", "Fantasy", "Epic Fantasy"]
    if "ken liu" in author or "dandelion dynasty" in series_cf:
        return ["Silkpunk", "Fiction", "Speculative Fiction", "Fantasy", "Epic Fantasy", "High Fantasy"]
    if "cixin" in author or "remembrance of earth" in series_cf:
        return ["Fiction", "Speculative Fiction", "Science Fiction", "Hard Science Fiction", "Space Opera", "First Contact"]
    if "cook" in author and "black company" in series_cf:
        return ["Grimdark", "Fiction", "Speculative Fiction", "Fantasy", "Military Fantasy"]
    if "sanderson" in author:
        return ["Cosmere", "Fiction", "Speculative Fiction", "Fantasy", "Epic Fantasy", "High Fantasy"]
    if "wolfe" in author:
        return ["Fiction", "Speculative Fiction", "Fantasy", "Classic", "Science Fiction", "Science Fantasy"]
    if "herbert" in author:
        return ["Fiction", "Speculative Fiction", "Classic", "Science Fiction", "Space Opera"]
    return ["Fiction"]


def tags_for(
    book: Any,
    *,
    calibre_library: str = "",
    include_scriptorium: bool = True,
) -> List[str]:
    """Return Calibre-standardized tags for a translated queue book."""
    calibre_raw = read_calibre_tags(calibre_library, getattr(book, "calibre_id", None))
    cleaned_calibre = [tag for tag in calibre_raw if not _is_noise_tag(tag)]
    base = cleaned_calibre if cleaned_calibre else _fallback_genre_tags(book)
    return normalize_tags(base, include_scriptorium=include_scriptorium)


def standardized_title(book: Any, current_title: str = "") -> str:
    """Keep distinct translated titles; disambiguate identical titles with `` (PT-BR)``."""
    source_title = str(getattr(book, "title", "") or "").strip()
    author = str(getattr(book, "author", "") or "").casefold()
    candidate = (current_title or "").strip()
    if "hobb" in author:
        if source_title.casefold() == "fool's errand":
            return "A Missão do Bobo"
        if candidate:
            candidate = re.sub(r"\bbufão\b", "bobo", re.sub(r"\bBufão\b", "Bobo", candidate))
    if candidate and candidate.casefold().endswith("(pt-br)"):
        return candidate
    if not candidate or (source_title and candidate.casefold() == source_title.casefold()):
        if source_title:
            return source_title if source_title.casefold().endswith("(pt-br)") else f"{source_title} (PT-BR)"
    return candidate or source_title


def read_opf_description(epub_path: str) -> str:
    """Read the existing ``<dc:description>`` text from an EPUB OPF, or empty string."""
    with zipfile.ZipFile(epub_path, "r") as zf:
        opf_path = _read_container(zf)
        opf = _read_opf(zf, opf_path)
    for child in opf:
        if _local_name(child.tag) != "metadata":
            continue
        for el in child:
            if _local_name(el.tag) == "description":
                return (el.text or "").strip()
    return ""


def _strip_legacy_footers(text: str) -> str:
    cleaned = (text or "").strip()
    while True:
        updated = cleaned
        for pattern in _FOOTER_PATTERNS:
            updated = pattern.sub("", updated).strip()
        if updated == cleaned:
            break
        cleaned = updated
    if cleaned.lower().startswith("<div>") and cleaned.lower().endswith("</div>"):
        inner = cleaned[5:-6].strip()
        if not inner:
            return ""
    return cleaned


def _fix_blurb_terms(body: str, book: Any) -> str:
    author = str(getattr(book, "author", "") or "").casefold()
    series = str(getattr(book, "series", "") or "").casefold()
    if "ruocchio" in author or "sun eater" in series:
        body = re.sub(r"\bsérie galáctica Devorador de Sóis\b", "série galáctica Sun Eater", body)
        body = re.sub(r"\bDevorador de Sóis\b", "O Devorador do Sol", body)
    return body


def translation_description(title: str) -> str:
    """Return the standard PT-BR edition notice used when no synopsis exists."""
    return f"Edição em português brasileiro de {title}.\n\n{_SCRIPTORIUM_NOTE}"


def _append_scriptorium_note(body: str) -> str:
    if _SCRIPTORIUM_NOTE.casefold() in body.casefold():
        return body
    trimmed = body.rstrip()
    lower = trimmed.lower()
    if "<p" in lower or "</p>" in lower:
        note_html = f"<p><i>{_SCRIPTORIUM_NOTE}</i></p>"
        if lower.endswith("</div>"):
            return f"{trimmed[:-6].rstrip()}\n{note_html}\n</div>"
        return f"{trimmed}\n{note_html}"
    if "<br" in lower or "<b>" in lower or "<i>" in lower:
        return f"{trimmed}<br/><br/><i>{_SCRIPTORIUM_NOTE}</i>"
    return f"{trimmed}\n\n{_SCRIPTORIUM_NOTE}"


def standardized_description(book: Any, source_epub: str) -> str:
    """Preserve PT-BR synopsis (or curated PT-BR synopsis) with a discreet Scriptorium note."""
    raw = read_opf_description(source_epub)
    body = _strip_legacy_footers(raw)
    body = _fix_blurb_terms(body, book)

    source_title = str(getattr(book, "title", "") or "").strip()
    if not body:
        body = _CURATED_DESCRIPTIONS_PTBR.get(source_title.casefold(), "")
    if not body:
        return translation_description(source_title or "obra literária")
    return _append_scriptorium_note(body)


def standardize_book_opf(
    book: Any,
    source_epub: str,
    output_epub: str,
    *,
    calibre_library: str = "",
    include_scriptorium: bool = True,
    translator: str = GENERATOR_NAME,
) -> Dict[str, Any]:
    """Write ``output_epub`` with Calibre-standardized OPF/NCX metadata for ``book``."""
    info = read_epub(source_epub, include_text=False)
    title = standardized_title(book, info.title or str(getattr(book, "title", "") or ""))
    resolved_library = infer_calibre_library(str(getattr(book, "source_path", "") or ""), calibre_library)
    subjects = tags_for(
        book,
        calibre_library=resolved_library,
        include_scriptorium=include_scriptorium,
    )
    description = standardized_description(book, source_epub)
    author = str(getattr(book, "author", "") or "").strip()
    series = str(getattr(book, "series", "") or "").strip()
    series_index = getattr(book, "series_index", None) if series else None

    update_opf_metadata(
        source_epub,
        output_epub,
        title=title,
        language="pt-BR",
        series=series if series else None,
        series_index=series_index,
        subjects=subjects,
        description=description,
        translator=translator,
        title_sort=title,
        author_sort=author_sort(author),
    )
    return {
        "title": title,
        "language": "pt-BR",
        "series": series or None,
        "series_index": series_index,
        "subjects": subjects,
        "author_sort": author_sort(author),
        "title_sort": title,
        "translator": translator,
        "output": os.path.abspath(output_epub),
    }


def standardize_completed_outputs(
    db_path: str = "data/literary_queue.db",
    outputs_dir: str = "translated_files",
    *,
    kindle_out: str = "translated_files/kindle",
    calibre_library: str = "",
    include_needs_review: bool = False,
    include_scriptorium: bool = True,
    run_epubcheck: bool = True,
    book_id: int = 0,
    epubcheck_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Standardize OPF metadata in finished ``.refined.epub`` files and refresh ``kindle_out``."""
    from .kindle import best_artifact, build_kindle_library

    if epubcheck_fn is None:
        from .queue_runner import _epubcheck

        epubcheck_fn = _epubcheck

    resolved_library = calibre_library or os.environ.get("CALIBRE_LIBRARY_PATH", "")
    allowed_states = {"completed", "needs_review"} if include_needs_review else {"completed"}

    store = QueueStore(db_path)
    try:
        books = store.list_books()
    finally:
        store.close()

    if book_id:
        books = [book for book in books if book.id == book_id]

    outputs = Path(outputs_dir)
    results: List[Dict[str, Any]] = []
    updated = 0
    failed = 0
    skipped = 0

    for book in books:
        if book.status not in allowed_states:
            skipped += 1
            results.append({"book_id": book.id, "title": book.title, "status": "skipped", "reason": book.status})
            continue
        artifact = best_artifact(outputs, book.title)
        if artifact is None or not artifact.is_file():
            skipped += 1
            results.append({"book_id": book.id, "title": book.title, "status": "skipped", "reason": "artifact missing"})
            continue

        fd, tmp_name = tempfile.mkstemp(prefix=f".{artifact.stem}.meta-", suffix=".epub", dir=str(outputs))
        os.close(fd)
        stage = Path(tmp_name)
        try:
            meta = standardize_book_opf(
                book,
                str(artifact),
                str(stage),
                calibre_library=resolved_library,
                include_scriptorium=include_scriptorium,
            )
            source_path = Path(book.source_path) if getattr(book, "source_path", "") else None
            pair_passed = True
            if source_path and source_path.is_file():
                validation = validate_epub_pair(str(source_path), str(stage), expected_language="pt-BR")
                pair_passed = bool(validation.get("passed"))
            epubcheck = epubcheck_fn(stage) if run_epubcheck else {"errors": 0, "skipped": True}
            epubcheck_ok = (epubcheck.get("errors") or 0) == 0
            if pair_passed and epubcheck_ok:
                os.replace(stage, artifact)
                updated += 1
                results.append(
                    {
                        "book_id": book.id,
                        "title": book.title,
                        "standardized_title": meta["title"],
                        "artifact": str(artifact),
                        "subjects": meta["subjects"],
                        "epubcheck": epubcheck,
                        "status": "updated",
                    }
                )
            else:
                failed += 1
                results.append(
                    {
                        "book_id": book.id,
                        "title": book.title,
                        "artifact": str(artifact),
                        "pair_passed": pair_passed,
                        "epubcheck": epubcheck,
                        "status": "failed",
                    }
                )
        finally:
            if stage.exists():
                stage.unlink()

    kindle_result = None
    if kindle_out:
        kindle_result = build_kindle_library(
            db_path=db_path,
            outputs_dir=outputs_dir,
            output_root=kindle_out,
            include_needs_review=include_needs_review,
            calibre_library=resolved_library,
            include_scriptorium=include_scriptorium,
        )

    return {
        "updated": updated,
        "failed": failed,
        "skipped": skipped,
        "results": results,
        "kindle": kindle_result,
    }
