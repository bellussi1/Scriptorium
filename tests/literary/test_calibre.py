from pathlib import Path

from src.literary.calibre import CalibreLibrary

from .conftest import make_calibre_db


def test_inventory_reads_calibre_schema_without_writing(tmp_path: Path):
    make_calibre_db(tmp_path)
    db = tmp_path / "metadata.db"
    before = db.read_bytes()
    library = CalibreLibrary(str(tmp_path))
    records = library.inventory(scan_epubs=False)
    assert len(records) == 1
    record = records[0]
    assert record.calibre_id == 1
    assert record.title == "Test Book"
    assert record.author == "Test Author"
    assert record.series == "Test Series"
    assert record.series_index == 1.0
    assert record.languages == ["en"]
    assert record.epub_path.endswith(".epub")
    assert db.read_bytes() == before


def test_inventory_scan_epub_metadata(tmp_path: Path):
    make_calibre_db(tmp_path)
    library = CalibreLibrary(str(tmp_path))
    records = library.inventory(scan_epubs=True)
    record = records[0]
    assert record.word_count > 0
    assert record.chapter_count == 2
    assert record.epub_language == "en"
    assert record.toc_titles == ["Chapter One", "Chapter Two"]
