"""Regression tests for scripts/split_omnibus.py."""
from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("split_omnibus", ROOT / "scripts" / "split_omnibus.py")
split_omnibus = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(split_omnibus)

OPF_NS = "{http://www.idpf.org/2007/opf}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
NCX_NS = "{http://www.daisy.org/z3986/2005/ncx/}"

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 16
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def _xhtml(title: str, body: str, *, lang: str = "en", head_extra: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}">\n'
        f"<head><title>{title}</title>{head_extra}</head>\n"
        f"<body>{body}</body>\n"
        "</html>\n"
    )


def _opf(book_labels: list[tuple[str, str]]) -> str:
    items = [
        ('ncx', 'toc.ncx', 'application/x-dtbncx+xml'),
        ('front', 'text/front.xhtml', 'application/xhtml+xml'),
        ('back', 'text/back.xhtml', 'application/xhtml+xml'),
        ('css', 'styles/style.css', 'text/css'),
    ]
    spine = ['front']
    for index, (label, _) in enumerate(book_labels, start=1):
        items.append((f"b{index}cover", f"text/Book{index}_Cover.xhtml", "application/xhtml+xml"))
        items.append((f"b{index}chapter", f"text/Book{index}_Chapter_1.xhtml", "application/xhtml+xml"))
        items.append((f"img{index}", f"images/Book{index}_cover.jpg", "image/jpeg"))
        spine.extend([f"b{index}cover", f"b{index}chapter"])
    items.append(("pattern", "images/pattern.png", "image/png"))
    items.append(("unused", "images/unused.jpg", "image/jpeg"))
    spine.append("back")
    manifest = "\n".join(
        f'    <item id="{item_id}" href="{href}" media-type="{media_type}"/>'
        for item_id, href, media_type in items
    )
    spine_xml = "\n".join(f'    <itemref idref="{item_id}"/>' for item_id in spine)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="BookId">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "    <dc:title>Omnibus</dc:title>\n"
        "    <dc:creator>Author</dc:creator>\n"
        "    <dc:language>en</dc:language>\n"
        '    <dc:identifier id="BookId">urn:isbn:9780000000000</dc:identifier>\n'
        "  </metadata>\n"
        f"  <manifest>\n{manifest}\n  </manifest>\n"
        f"  <spine toc=\"ncx\">\n{spine_xml}\n  </spine>\n"
        '  <guide><reference type="cover" href="text/front.xhtml"/></guide>\n'
        "</package>\n"
    )


def _ncx(labels: list[str]) -> str:
    points = []
    for index, label in enumerate(labels, start=1):
        points.append(
            f'  <navPoint id="np{index}" playOrder="{index}">\n'
            f"    <navLabel><text>{label}</text></navLabel>\n"
            f'    <content src="text/Book{index}_Cover.xhtml"/>\n'
            f'    <navPoint id="np{index}c" playOrder="{index}0">\n'
            "      <navLabel><text>Chapter One</text></navLabel>\n"
            f'      <content src="text/Book{index}_Chapter_1.xhtml"/>\n'
            "    </navPoint>\n"
            "  </navPoint>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        "  <head>\n"
        '    <meta name="dtb:uid" content="urn:isbn:9780000000000"/>\n'
        '    <meta name="dtb:depth" content="2"/>\n'
        "  </head>\n"
        "  <docTitle><text>Omnibus</text></docTitle>\n"
        f"  <navMap>\n{chr(10).join(points)}\n  </navMap>\n"
        "</ncx>\n"
    )


def _build_epub(path: Path, ncx_labels: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            "  <rootfiles>\n"
            '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
            "  </rootfiles>\n"
            "</container>\n",
        )
        archive.writestr("OEBPS/content.opf", _opf([(label, "") for label in ncx_labels]))
        archive.writestr("OEBPS/toc.ncx", _ncx(ncx_labels))
        archive.writestr("OEBPS/text/front.xhtml", _xhtml("Omnibus", "<p>Front</p>"))
        archive.writestr("OEBPS/text/back.xhtml", _xhtml("Omnibus", "<p>Back</p>"))
        archive.writestr("OEBPS/styles/style.css", 'body { background: url("../images/pattern.png"); }')
        archive.writestr("OEBPS/images/pattern.png", PNG_BYTES)
        archive.writestr("OEBPS/images/unused.jpg", JPEG_BYTES)
        for index in range(1, len(ncx_labels) + 1):
            archive.writestr(
                f"OEBPS/text/Book{index}_Cover.xhtml",
                _xhtml("Omnibus", f'<img src="../images/Book{index}_cover.jpg"/>'),
            )
            archive.writestr(
                f"OEBPS/text/Book{index}_Chapter_1.xhtml",
                _xhtml(
                    "Omnibus",
                    f"<p>Text {index}</p>",
                    head_extra='<link href="../styles/style.css" rel="stylesheet" type="text/css"/>',
                ),
            )
            archive.writestr(f"OEBPS/images/Book{index}_cover.jpg", JPEG_BYTES)


def _read_opf(epub: Path) -> ET.Element:
    with zipfile.ZipFile(epub) as archive:
        return ET.fromstring(archive.read("OEBPS/content.opf"))


def _cover_id(opf: ET.Element) -> str:
    meta = opf.find(f"{OPF_NS}metadata")
    assert meta is not None
    for entry in meta.findall(f"{OPF_NS}meta"):
        if entry.get("name") == "cover":
            return entry.get("content") or ""
    return ""


def test_spine_prefix_split_wires_cover_metadata_and_prunes(tmp_path: Path) -> None:
    source = tmp_path / "omnibus.epub"
    _build_epub(source, ["Book One", "Book Two"])
    out_dir = tmp_path / "out"

    results = split_omnibus.split_omnibus(
        source,
        out_dir,
        "Test Series",
        "Author",
        spine_prefix_regex=r"Book(?P<n>\d+)_",
        titles={1: "Um", 2: "Dois"},
        language="pt-BR",
        description_template="Edição em português brasileiro de {title}.\n\nNota.",
        subjects=["Fiction", "Fantasy"],
        translator="Scriptorium",
        filename_template="{title} (pt-BR).refined.epub",
        prune_assets=True,
        cover_image_regex=r"Book{n}_cover\.",
        cover_page_regex=r"Book{n}_Cover\.",
        strict_ncx_labels=True,
    )

    assert [item["index"] for item in results] == [1, 2]
    assert all(not item["validation_errors"] for item in results)
    assert (out_dir / "Um (pt-BR).refined.epub").is_file()

    first = out_dir / "Um (pt-BR).refined.epub"
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert "OEBPS/text/Book1_Chapter_1.xhtml" in names
        assert "OEBPS/text/Book2_Chapter_1.xhtml" not in names
        assert "OEBPS/images/Book1_cover.jpg" in names
        assert "OEBPS/images/Book2_cover.jpg" not in names
        assert "OEBPS/images/unused.jpg" not in names
        assert "OEBPS/images/pattern.png" in names
        assert "OEBPS/styles/style.css" in names

        chapter = archive.read("OEBPS/text/Book1_Chapter_1.xhtml").decode("utf-8")
        assert 'xml:lang="pt-BR"' in chapter
        assert 'lang="pt-BR"' in chapter
        assert "<title>Um</title>" in chapter

        ncx = ET.fromstring(archive.read("OEBPS/toc.ncx"))
        assert ncx.find(f".//{NCX_NS}docTitle/{NCX_NS}text").text == "Um"
        labels = [point.find(f"{NCX_NS}navLabel/{NCX_NS}text").text
                  for point in ncx.findall(f".//{NCX_NS}navPoint")]
        assert labels[0] == "Um"
        assert "Chapter One" in labels
        assert "Dois" not in labels

    opf = _read_opf(first)
    metadata = opf.find(f"{OPF_NS}metadata")
    assert metadata is not None
    assert metadata.find(f"{DC_NS}title").text == "Um"
    assert metadata.find(f"{DC_NS}language").text == "pt-BR"
    identifier = metadata.find(f"{DC_NS}identifier").text or ""
    assert identifier.startswith("urn:uuid:")
    assert metadata.find(f"{DC_NS}description").text.startswith(
        "Edição em português brasileiro de Um."
    )
    assert [item.text for item in metadata.findall(f"{DC_NS}subject")] == ["Fiction", "Fantasy"]

    cover_id = _cover_id(opf)
    manifest = opf.find(f"{OPF_NS}manifest")
    assert manifest is not None
    cover_item = next(
        item for item in manifest.findall(f"{OPF_NS}item") if item.get("id") == cover_id
    )
    assert cover_item.get("href") == "images/Book1_cover.jpg"
    guide = {
        reference.get("type"): reference.get("href")
        for reference in opf.findall(f".//{OPF_NS}guide/{OPF_NS}reference")
    }
    assert guide["cover"] == "text/Book1_Cover.xhtml"
    assert "toc" not in guide
    assert guide["text"] == "text/Book1_Chapter_1.xhtml"


def test_legacy_ncx_book_labels_still_split(tmp_path: Path) -> None:
    source = tmp_path / "omnibus.epub"
    _build_epub(source, ["BOOK 1: ONE", "BOOK 2: TWO"])
    out_dir = tmp_path / "out"

    results = split_omnibus.split_omnibus(
        source,
        out_dir,
        "Test Series",
        "Author",
    )

    assert [item["title"] for item in results] == ["One", "Two"]
    assert [item["index"] for item in results] == [1, 2]
    assert all(not item["validation_errors"] for item in results)
