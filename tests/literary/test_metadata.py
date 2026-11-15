"""Tests for Calibre-aligned OPF metadata standardization."""
from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace

from src.literary.epub import read_epub, update_opf_metadata, validate_epub_structure
from src.literary.metadata import (
    normalize_tags,
    standardize_completed_outputs,
    standardized_description,
    standardized_title,
    tags_for,
)
from src.literary.models import BookRecord
from src.literary.queue import QueueStore

from .conftest import make_calibre_db, make_epub


def test_normalize_tags_drops_noise_and_legacy_tags():
    result = normalize_tags(
        [
            "FIC000000 Fiction / General",
            "no data",
            "EN",
            "PT-PT",
            "Brazilian Portuguese",
            "Machine Translation",
            "Fiction",
            "Speculative Fiction",
            "Science Fiction",
        ]
    )
    assert result == ["Fiction", "Speculative Fiction", "Science Fiction", "PT-BR", "Scriptorium"]


def test_normalize_tags_can_omit_scriptorium():
    result = normalize_tags(["Fiction", "Western", "EN"], include_scriptorium=False)
    assert result == ["Fiction", "Western", "PT-BR"]


def test_tags_for_covers_queue_authors_and_calibre_lookup(tmp_path: Path):
    cal_db = make_calibre_db(tmp_path)
    conn = sqlite3.connect(cal_db)
    conn.executescript(
        """
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY, book INTEGER, tag INTEGER);
        INSERT INTO tags VALUES (1, 'Fiction'), (2, 'Classic'), (3, 'EN'), (4, 'Western'), (5, 'Historical Fiction');
        INSERT INTO books_tags_link VALUES (1, 1, 1), (2, 1, 2), (3, 1, 3), (4, 1, 4), (5, 1, 5);
        """
    )
    conn.commit()
    conn.close()

    from_calibre = tags_for(
        SimpleNamespace(calibre_id=1, author="Unknown Author", series=""),
        calibre_library=str(tmp_path),
    )
    assert from_calibre == [
        "Fiction",
        "Classic",
        "Western",
        "Historical Fiction",
        "PT-BR",
        "Scriptorium",
    ]

    erikson = tags_for(SimpleNamespace(author="Steven Erikson", series="Malazan Book of the Fallen"))
    assert "Military Fantasy" in erikson
    assert "High Fantasy" in erikson
    assert "PT-BR" in erikson
    assert "Scriptorium" in erikson

    abercrombie_series = tags_for(SimpleNamespace(author="Joe Abercrombie", series="The Age of Madness"))
    assert "Grimdark" in abercrombie_series
    assert "Epic Fantasy" in abercrombie_series

    mcmurtry = tags_for(SimpleNamespace(author="Larry McMurtry", series=""))
    assert set(mcmurtry) == {"Fiction", "Classic", "Historical Fiction", "Western", "PT-BR", "Scriptorium"}


def test_standardized_title_disambiguates_only_untranslated_and_is_idempotent():
    book = SimpleNamespace(title="Lonesome Dove")
    assert standardized_title(book, "Lonesome Dove") == "Lonesome Dove (PT-BR)"
    assert standardized_title(book, "Lonesome Dove (PT-BR)") == "Lonesome Dove (PT-BR)"
    assert standardized_title(SimpleNamespace(title="Howling Dark"), "Escuridão Uivante") == "Escuridão Uivante"


def test_standardized_description_preserves_ptbr_synopsis_and_curated_fallback(tmp_path: Path):
    html_epub = make_epub(tmp_path / "howling.epub", title="Escuridão Uivante", language="pt-BR")
    update_opf_metadata(
        str(html_epub),
        str(html_epub),
        description=(
            "<b>O segundo romance da série galáctica Devorador de Sóis.</b><br>"
            "Hadrian está perdido.\n\nTranslated using Scriptorium\nhttps://github.com/bellussi1/Scriptorium"
        ),
    )
    cleaned = standardized_description(
        SimpleNamespace(title="Howling Dark", author="Christopher Ruocchio", series="The Sun Eater"),
        str(html_epub),
    )
    assert "Devorador de Sóis" not in cleaned
    assert "Sun Eater" in cleaned
    assert "Translated using Scriptorium" not in cleaned
    assert "Tradução em português brasileiro via Scriptorium." in cleaned

    # Calling again is idempotent.
    update_opf_metadata(str(html_epub), str(html_epub), description=cleaned)
    cleaned_twice = standardized_description(
        SimpleNamespace(title="Howling Dark", author="Christopher Ruocchio", series="The Sun Eater"),
        str(html_epub),
    )
    assert cleaned_twice.count("Tradução em português brasileiro via Scriptorium.") == 1

    # Curated synopsis restores Disquiet Gods when only footer remained.
    disquiet = make_epub(tmp_path / "disquiet.epub", title="Deuses Inquietos", language="pt-BR")
    update_opf_metadata(
        str(disquiet),
        str(disquiet),
        description="Translated using Scriptorium\nhttps://github.com/bellussi1/Scriptorium",
    )
    restored = standardized_description(
        SimpleNamespace(title="Disquiet Gods", author="Christopher Ruocchio", series="The Sun Eater"),
        str(disquiet),
    )
    assert "Quase duzentos anos" in restored
    assert "Vigilantes" in restored
    assert "Tradução em português brasileiro via Scriptorium." in restored


def test_standardize_completed_outputs_rewrites_refined_and_kindle_and_syncs_ncx(tmp_path: Path):
    db = tmp_path / "queue.db"
    store = QueueStore(str(db))
    source = make_epub(tmp_path / "source.epub", title="Lonesome Dove", language="en")
    book_id = store.add_book(
        BookRecord(
            calibre_id=311,
            title="Lonesome Dove",
            author="Larry McMurtry",
            series="",
            series_index=1.0,
            languages=["en"],
            epub_path=str(source),
        )
    )
    for state in ("preparing", "translating", "validating", "completed"):
        store.set_book_state(book_id, state)
    store.mark_reviewed(book_id, "approved")
    store.close()

    outputs = tmp_path / "translated_files"
    outputs.mkdir()
    refined = outputs / "Lonesome Dove (pt-BR).refined.epub"
    make_epub(refined, title="Lonesome Dove", language="pt-BR")
    # Inject NCX + legacy OPF subjects/footer to verify full replacement.
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        "<docTitle><text>Lonesome Dove</text></docTitle><navMap/></ncx>"
    )
    with zipfile.ZipFile(refined, "a") as zf:
        zf.writestr("OEBPS/toc.ncx", ncx)
    update_opf_metadata(
        str(refined),
        str(refined),
        subjects=["Caubóis", "Faroeste"],
        description="RESUMO: Um clássico do Oeste.\n\nTranslated using Scriptorium\nhttps://github.com/bellussi1/Scriptorium",
    )

    kindle_root = outputs / "kindle"
    result = standardize_completed_outputs(
        db_path=str(db),
        outputs_dir=str(outputs),
        kindle_out=str(kindle_root),
        run_epubcheck=False,
    )
    assert result["updated"] == 1
    assert result["failed"] == 0

    info = read_epub(str(refined), include_text=False)
    assert info.title == "Lonesome Dove (PT-BR)"
    assert info.language == "pt-BR"
    assert not [i for i in validate_epub_structure(str(refined)) if i.severity.value in {"error", "critical"}]

    with zipfile.ZipFile(refined) as zf:
        opf_text = zf.read(info.opf_path).decode("utf-8")
        ncx_text = zf.read("OEBPS/toc.ncx").decode("utf-8")
        root = ET.fromstring(opf_text)

    subjects = [el.text for el in root.iter() if el.tag.endswith("subject")]
    assert subjects == ["Fiction", "Classic", "Historical Fiction", "Western", "PT-BR", "Scriptorium"]
    assert "<text>Lonesome Dove (PT-BR)</text>" in ncx_text
    assert "RESUMO: Um clássico do Oeste." in opf_text
    assert "Tradução em português brasileiro via Scriptorium." in opf_text
    assert "Caubóis" not in opf_text

    kindle_epub = kindle_root / "Larry McMurtry" / "Standalone" / "01 - Lonesome Dove (pt-BR).epub"
    assert kindle_epub.is_file()
    assert read_epub(str(kindle_epub), include_text=False).title == "Lonesome Dove (PT-BR)"
