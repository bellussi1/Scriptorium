from pathlib import Path
import zipfile

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


def test_update_opf_metadata_standardizes_series_tags_and_translator(tmp_path: Path):
    source = make_epub(tmp_path / "source.epub")
    output = tmp_path / "output.epub"
    update_opf_metadata(
        str(source),
        str(output),
        title="T?tulo Padronizado",
        language="pt-BR",
        series="The Sun Eater",
        series_index=2,
        subjects=["Science Fiction", "Space Opera", "Brazilian Portuguese"],
        description="Descri??o editorial.",
        translator="Scriptorium",
        title_sort="Titulo Padronizado",
        author_sort="Ruocchio, Christopher",
    )
    with zipfile.ZipFile(output) as archive:
        opf_path = next(name for name in archive.namelist() if name.endswith(".opf"))
        opf = archive.read(opf_path).decode("utf-8")
    assert 'name="calibre:series"' in opf
    assert "The Sun Eater" in opf
    assert 'name="calibre:series_index"' in opf
    assert "collection-type" in opf
    assert "Science Fiction" in opf
    assert "Space Opera" in opf
    assert "Brazilian Portuguese" in opf
    assert "Scriptorium" in opf
    assert "marc:relators" in opf
    assert 'name="calibre:title_sort"' in opf
    assert 'name="calibre:author_sort"' in opf
    assert "Descri??o editorial." in opf

def test_update_opf_metadata_keeps_epub2_packages_epub2(tmp_path: Path):
    source = make_epub(tmp_path / "source.epub")
    epub2_source = tmp_path / "source-epub2.epub"
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(epub2_source, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith(".opf"):
                data = data.replace(b'version="3.0"', b'version="2.0"')
            dst.writestr(info, data)

    output = tmp_path / "output.epub"
    update_opf_metadata(
        str(epub2_source),
        str(output),
        title="Titulo",
        language="pt-BR",
        series="The Sun Eater",
        series_index=2,
        translator="Scriptorium",
        title_sort="Titulo",
        author_sort="Ruocchio, Christopher",
    )
    with zipfile.ZipFile(output) as archive:
        opf_path = next(name for name in archive.namelist() if name.endswith(".opf"))
        opf = archive.read(opf_path).decode("utf-8")
    assert 'version="2.0"' in opf
    assert "property=" not in opf
    assert "refines=" not in opf
    assert 'name="calibre:series"' in opf
    assert 'name="calibre:series_index"' in opf
    assert "role" in opf


def test_update_opf_metadata_uses_content_for_calibre_name_metas(tmp_path: Path):
    import xml.etree.ElementTree as ET

    source = make_epub(tmp_path / "source.epub")
    output = tmp_path / "output.epub"
    update_opf_metadata(
        str(source),
        str(output),
        title="Titulo",
        language="pt-BR",
        series="The Sun Eater",
        series_index=2,
        translator="Scriptorium",
        title_sort="Titulo",
        author_sort="Ruocchio, Christopher",
    )
    with zipfile.ZipFile(output) as archive:
        opf_path = next(name for name in archive.namelist() if name.endswith(".opf"))
        root = ET.fromstring(archive.read(opf_path))

    def local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    for element in root.iter():
        if local_name(element.tag) != "meta":
            continue
        if element.attrib.get("name"):
            assert "content" in element.attrib, element.attrib
            assert not (element.text or "").strip(), element.attrib
        if element.attrib.get("property"):
            assert "content" not in element.attrib, element.attrib
            assert (element.text or "").strip(), element.attrib
