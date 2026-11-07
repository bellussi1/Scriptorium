from pathlib import Path

from src.literary.epub import (
    read_epub,
    update_opf_metadata,
    validate_epub_structure,
)

from .conftest import make_epub


def test_read_epub_metadata_toc_and_words(tmp_path: Path):
    path = make_epub(tmp_path / "book.epub", title="Book", language="en")
    info = read_epub(str(path))
    assert info.title == "Book"
    assert info.language == "en"
    assert info.word_count > 0
    assert len(info.toc) == 2
    assert info.toc[0]["title"] == "Chapter One"


def test_validate_epub_structure_accepts_valid_book(tmp_path: Path):
    path = make_epub(tmp_path / "book.epub")
    issues = validate_epub_structure(str(path))
    assert not [issue for issue in issues if issue.severity.value in {"error", "critical"}]


def test_validate_epub_structure_flags_missing_manifest_item(tmp_path: Path):
    path = make_epub(tmp_path / "book.epub", missing_manifest_item=True)
    issues = validate_epub_structure(str(path))
    assert any(issue.code == "epub.manifest_missing" for issue in issues)


def test_validate_epub_structure_flags_zip_slip(tmp_path: Path):
    path = make_epub(tmp_path / "book.epub", zip_slip=True)
    issues = validate_epub_structure(str(path))
    assert any(issue.code == "epub.zip_slip" for issue in issues)


def test_update_opf_metadata_preserves_source(tmp_path: Path):
    source = make_epub(tmp_path / "source.epub")
    before = source.read_bytes()
    output = tmp_path / "output.epub"
    update_opf_metadata(
        str(source),
        str(output),
        title="Novo Título",
        language="pt-BR",
        series="Série",
        series_index=2,
    )
    assert source.read_bytes() == before
    info = read_epub(str(output))
    assert info.title == "Novo Título"
    assert info.language == "pt-BR"
    assert info.issues == []
