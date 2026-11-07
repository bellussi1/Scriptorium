from __future__ import annotations

import os
import sqlite3
import zipfile
from pathlib import Path
from typing import Optional

import pytest


CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def make_epub(
    path: Path,
    *,
    title: str = "Test Book",
    language: str = "en",
    chapters: Optional[list[str]] = None,
    include_nav: bool = True,
    missing_manifest_item: bool = False,
    zip_slip: bool = False,
) -> Path:
    chapters = chapters or [
        "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Chapter One</h1><p>The rain fell on the roof.</p><p>He waited.</p></body></html>",
        "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Chapter Two</h1><p>Morning came slowly.</p></body></html>",
    ]
    manifest = [
        '<item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="style" href="style.css" media-type="text/css"/>',
    ]
    if include_nav:
        manifest.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    if missing_manifest_item:
        manifest.append('<item id="ghost" href="ghost.xhtml" media-type="application/xhtml+xml"/>')
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:language>{language}</dc:language>
    <dc:identifier id="bookid">urn:uuid:test-book</dc:identifier>
  </metadata>
  <manifest>
    {''.join(manifest)}
  </manifest>
  <spine>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
  </spine>
</package>
"""
    nav = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc"><ol><li><a href="ch1.xhtml">Chapter One</a></li><li><a href="ch2.xhtml">Chapter Two</a></li></ol></nav></body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/ch1.xhtml", chapters[0])
        zf.writestr("OEBPS/ch2.xhtml", chapters[1] if len(chapters) > 1 else chapters[0])
        zf.writestr("OEBPS/style.css", "body { font-family: serif; }")
        if include_nav:
            zf.writestr("OEBPS/nav.xhtml", nav)
        if zip_slip:
            zf.writestr("../evil.txt", "bad")
    return path


def make_calibre_db(root: Path, *, title: str = "Test Book", language: str = "en") -> Path:
    db = root / "metadata.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, sort TEXT, timestamp TEXT, pubdate TEXT,
                            series_index REAL, author_sort TEXT, path TEXT, uuid TEXT, has_cover BOOL, last_modified TEXT);
        CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT, sort TEXT, link TEXT);
        CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER, author INTEGER);
        CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT, sort TEXT, link TEXT);
        CREATE TABLE books_series_link (id INTEGER PRIMARY KEY, book INTEGER, series INTEGER);
        CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT, link TEXT);
        CREATE TABLE books_languages_link (id INTEGER PRIMARY KEY, book INTEGER, lang_code INTEGER, item_order INTEGER);
        CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, uncompressed_size INTEGER, name TEXT);
        CREATE TABLE identifiers (id INTEGER PRIMARY KEY, book INTEGER, type TEXT, val TEXT);
        """
    )
    conn.execute(
        "INSERT INTO books VALUES (1, ?, 'Test Book', '2026-01-01', '2026-01-01', 1.0, 'Author, Test', 'Test Author/Test Book (1)', 'uuid', 0, '2026-01-01')",
        (title,),
    )
    conn.execute("INSERT INTO authors VALUES (1, 'Test Author', 'Author, Test', '')")
    conn.execute("INSERT INTO books_authors_link VALUES (1, 1, 1)")
    conn.execute("INSERT INTO series VALUES (1, 'Test Series', 'Test Series', '')")
    conn.execute("INSERT INTO books_series_link VALUES (1, 1, 1)")
    conn.execute("INSERT INTO languages VALUES (1, ?, '')", (language,))
    conn.execute("INSERT INTO books_languages_link VALUES (1, 1, 1, 0)")
    conn.execute("INSERT INTO data VALUES (1, 1, 'EPUB', 1000, 'Test Book - Test Author')")
    conn.execute("INSERT INTO identifiers VALUES (1, 1, 'isbn', '9780000000000')")
    conn.commit()
    conn.close()
    folder = root / "Test Author" / "Test Book (1)"
    folder.mkdir(parents=True, exist_ok=True)
    make_epub(folder / "Test Book - Test Author.epub", title=title, language=language)
    return db
