"""Read-only Calibre inventory.

The Calibre database is opened with SQLite ``mode=ro``. No table is ever
written, no lock is taken beyond the read transaction, and the EPUB files are
only opened for reading.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .epub import read_epub
from .models import BookRecord, ValidationIssue


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


_LANG_ALIASES = {
    "por": "pt", "eng": "en", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de",
    "spa": "es", "ita": "it", "jpn": "ja", "chi": "zh", "zho": "zh", "rus": "ru",
    "kor": "ko", "nld": "nl", "dut": "nl", "pol": "pl", "swe": "sv", "dan": "da",
    "fin": "fi", "nor": "no", "tur": "tr", "ara": "ar", "heb": "he", "hin": "hi",
}


def _lang_prefix(code: str) -> str:
    base = (code or "").strip().lower().replace("_", "-").split("-")[0]
    return _LANG_ALIASES.get(base, base)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return bool(row)


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    except sqlite3.DatabaseError:
        return []


class CalibreLibrary:
    """A read-only view of a Calibre library."""

    def __init__(self, library_root: str):
        self.library_root = os.path.abspath(library_root)
        self.db_path = os.path.join(self.library_root, "metadata.db")
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Calibre metadata.db not found: {self.db_path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    def inventory(
        self,
        scan_epubs: bool = False,
        author_filter: Optional[List[str]] = None,
        series_filter: Optional[List[str]] = None,
    ) -> List[BookRecord]:
        conn = self._connect()
        try:
            book_columns = set(_columns(conn, "books"))
            has_series_index = "series_index" in book_columns
            rows = conn.execute(
                f"""
                SELECT id, title, author_sort, path, pubdate
                       {', series_index' if has_series_index else ', NULL AS series_index'}
                FROM books
                ORDER BY author_sort, title
                """
            ).fetchall()

            authors_by_book = self._authors_by_book(conn)
            series_by_book = self._series_by_book(conn)
            languages_by_book = self._languages_by_book(conn)
            formats_by_book = self._formats_by_book(conn)
            identifiers_by_book = self._identifiers_by_book(conn)

            records: List[BookRecord] = []
            for row in rows:
                book_id = int(row["id"])
                authors = authors_by_book.get(book_id, [])
                series = series_by_book.get(book_id, [])
                formats = formats_by_book.get(book_id, [])
                record = BookRecord(
                    calibre_id=book_id,
                    title=row["title"] or "",
                    author=" & ".join(authors),
                    author_sort=row["author_sort"] or "",
                    series=series[0][0] if series else "",
                    series_index=series[0][1] if series else (row["series_index"] if has_series_index else None),
                    languages=languages_by_book.get(book_id, []),
                    formats=formats,
                    calibre_path=row["path"] or "",
                    pubdate=str(row["pubdate"] or ""),
                    identifiers=identifiers_by_book.get(book_id, {}),
                )
                if author_filter and not any(
                    token.casefold() in record.author.casefold() for token in author_filter
                ):
                    continue
                if series_filter and not any(
                    token.casefold() in record.series.casefold() for token in series_filter
                ):
                    continue
                record.epub_path = self._epub_path(record, conn, book_id)
                if not record.epub_path:
                    record.issues.append("No EPUB file found for this Calibre record")
                elif scan_epubs:
                    self._scan_epub(record)
                records.append(record)

            self._mark_duplicates(records)
            return records
        finally:
            conn.close()

    def _authors_by_book(self, conn: sqlite3.Connection) -> Dict[int, List[str]]:
        result: Dict[int, List[str]] = defaultdict(list)
        if not (_table_exists(conn, "books_authors_link") and _table_exists(conn, "authors")):
            return result
        for row in conn.execute(
            """
            SELECT bal.book, a.name
            FROM books_authors_link bal
            JOIN authors a ON a.id = bal.author
            ORDER BY bal.book, bal.id
            """
        ):
            result[int(row["book"])].append(row["name"] or "")
        return result

    def _series_by_book(self, conn: sqlite3.Connection) -> Dict[int, List[tuple]]:
        result: Dict[int, List[tuple]] = defaultdict(list)
        if not (_table_exists(conn, "books_series_link") and _table_exists(conn, "series")):
            return result
        series_columns = set(_columns(conn, "series"))
        index_expr = "b.series_index" if "series_index" in set(_columns(conn, "books")) else "NULL"
        for row in conn.execute(
            f"""
            SELECT bsl.book, s.name, {index_expr} AS idx
            FROM books_series_link bsl
            JOIN series s ON s.id = bsl.series
            JOIN books b ON b.id = bsl.book
            ORDER BY bsl.book, s.name
            """
        ):
            idx = row["idx"]
            result[int(row["book"])].append((row["name"] or "", float(idx) if idx is not None else None))
        return result

    def _languages_by_book(self, conn: sqlite3.Connection) -> Dict[int, List[str]]:
        result: Dict[int, List[str]] = defaultdict(list)
        if not (_table_exists(conn, "books_languages_link") and _table_exists(conn, "languages")):
            return result
        for row in conn.execute(
            """
            SELECT bll.book, l.lang_code
            FROM books_languages_link bll
            JOIN languages l ON l.id = bll.lang_code
            ORDER BY bll.book, bll.item_order
            """
        ):
            result[int(row["book"])].append(row["lang_code"] or "")
        return result

    def _formats_by_book(self, conn: sqlite3.Connection) -> Dict[int, List[str]]:
        result: Dict[int, List[str]] = defaultdict(list)
        if not _table_exists(conn, "data"):
            return result
        for row in conn.execute("SELECT book, format FROM data ORDER BY book, format"):
            result[int(row["book"])].append((row["format"] or "").upper())
        return result

    def _identifiers_by_book(self, conn: sqlite3.Connection) -> Dict[int, Dict[str, str]]:
        result: Dict[int, Dict[str, str]] = defaultdict(dict)
        if not _table_exists(conn, "identifiers"):
            return result
        for row in conn.execute("SELECT book, type, val FROM identifiers ORDER BY book, type"):
            result[int(row["book"])][row["type"] or ""] = row["val"] or ""
        return result

    def _epub_path(self, record: BookRecord, conn: sqlite3.Connection, book_id: int) -> str:
        folder = os.path.join(self.library_root, record.calibre_path)
        if _table_exists(conn, "data"):
            for row in conn.execute(
                "SELECT name FROM data WHERE book = ? AND upper(format) = 'EPUB'", (book_id,)
            ):
                candidate = os.path.join(folder, f"{row['name']}.epub")
                if os.path.exists(candidate):
                    return candidate
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith(".epub"):
                    return os.path.join(folder, name)
        return ""

    def _scan_epub(self, record: BookRecord) -> None:
        info = read_epub(record.epub_path, include_text=False)
        record.epub_title = info.title
        record.epub_language = info.language
        record.epub_identifier = info.identifier
        record.word_count = info.word_count
        record.document_count = info.document_count
        record.chapter_count = len(info.toc) or info.document_count
        record.toc_titles = [entry.get("title", "") for entry in info.toc if entry.get("title")]
        if info.issues:
            record.issues.extend(issue.message for issue in info.issues)
        if info.title and _norm(info.title) != _norm(record.title):
            record.issues.append(f"EPUB title differs from Calibre title: '{info.title}'")
        if record.languages and info.language:
            db_langs = {_lang_prefix(lang) for lang in record.languages}
            epub_lang = _lang_prefix(info.language)
            if epub_lang not in db_langs:
                record.issues.append(f"EPUB language '{info.language}' differs from Calibre languages {record.languages}")
        if _norm(record.author_sort) in {"unknown", ""} and record.author:
            record.issues.append(f"Calibre author_sort is '{record.author_sort}'; author field is '{record.author}'")

    @staticmethod
    def _mark_duplicates(records: List[BookRecord]) -> None:
        groups: Dict[str, List[BookRecord]] = defaultdict(list)
        for record in records:
            key = f"{_norm(record.title)}|{_norm(record.author)}"
            groups[key].append(record)
        for key, group in groups.items():
            if len(group) < 2:
                continue
            by_language: Dict[str, List[BookRecord]] = defaultdict(list)
            for record in group:
                prefix = _lang_prefix(record.languages[0]) if record.languages else "?"
                by_language[prefix].append(record)
            for record in group:
                record.duplicate_group = key
                siblings = [
                    f"calibre:{other.calibre_id} ({','.join(other.languages) or '?'})"
                    for other in group
                    if other.calibre_id != record.calibre_id
                ]
                prefix = _lang_prefix(record.languages[0]) if record.languages else "?"
                same_language = [other for other in by_language.get(prefix, []) if other.calibre_id != record.calibre_id]
                if same_language:
                    record.issues.append("Duplicate edition in the same language: " + ", ".join(siblings))
                else:
                    record.issues.append("[info] Bilingual pair: " + ", ".join(siblings))

    def summarize(self, records: List[BookRecord]) -> Dict[str, Any]:
        series: Dict[str, List[BookRecord]] = defaultdict(list)
        for record in records:
            if record.series:
                series[record.series].append(record)
        series_payload = {}
        for name, books in sorted(series.items()):
            ordered = sorted(books, key=lambda b: (b.series_index is None, b.series_index or 0, b.title))
            indices = [b.series_index for b in ordered if b.series_index is not None]
            duplicates = [idx for idx, count in Counter(indices).items() if count > 1]
            series_payload[name] = {
                "count": len(ordered),
                "indices": indices,
                "duplicate_indices": duplicates,
                "books": [
                    {
                        "calibre_id": b.calibre_id,
                        "title": b.title,
                        "series_index": b.series_index,
                        "languages": b.languages,
                        "word_count": b.word_count,
                        "epub_path": b.epub_path,
                    }
                    for b in ordered
                ],
            }
        duplicates = [b.to_dict() for b in records if b.duplicate_group]
        issues = [
            {"calibre_id": b.calibre_id, "title": b.title, "issues": b.issues}
            for b in records
            if b.issues
        ]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "library_root": self.library_root,
            "book_count": len(records),
            "epub_count": sum(1 for b in records if b.epub_path),
            "word_count": sum(b.word_count for b in records),
            "series": series_payload,
            "duplicates": duplicates,
            "issues": issues,
        }

    def write_inventory(
        self,
        output_path: str,
        scan_epubs: bool = False,
        author_filter: Optional[List[str]] = None,
        series_filter: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        records = self.inventory(
            scan_epubs=scan_epubs,
            author_filter=author_filter,
            series_filter=series_filter,
        )
        payload = {
            **self.summarize(records),
            "books": [record.to_dict() for record in records],
        }
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        temp = output_path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp, output_path)
        return payload
