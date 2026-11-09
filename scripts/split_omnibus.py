"""Split a well-structured omnibus EPUB into one EPUB per top-level book.

The source must expose its books as top-level NCX entries such as
``BOOK 1: GARDENS OF THE MOON``. The splitter reuses the source spine, copies
the shared CSS/image assets, and writes a fresh EPUB 2 package per book. It
never writes into the source library; pass an explicit ``--out-dir``.

Usage:
    python scripts/split_omnibus.py \
        --source "C:/.../The Complete Malazan Book ....epub" \
        --out-dir data/calibre/malazan-split \
        --series "Malazan Book of the Fallen" \
        --author "Steven Erikson"
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.literary.epub import validate_epub_structure  # noqa: E402

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

BOOK_TITLE_RE = re.compile(r"^BOOK\s+(\d+)\s*:\s*(.+)$", re.IGNORECASE)
SMALL_TITLE_WORDS = {"of", "the", "and", "in", "a", "an", "to", "for", "on", "at", "by", "with", "from"}


def _display_title(raw: str) -> str:
    words = raw.split()
    out = []
    for index, word in enumerate(words):
        low = word.casefold()
        if 0 < index < len(words) - 1 and low in SMALL_TITLE_WORDS:
            out.append(low)
        else:
            out.append(word[:1].upper() + word[1:].lower())
    return " ".join(out)


def _text(element: Optional[ET.Element]) -> str:
    return (element.text or "").strip() if element is not None else ""


def _read_zip_xml(archive: zipfile.ZipFile, path: str) -> ET.Element:
    return ET.fromstring(archive.read(path))


def _container_opf_path(archive: zipfile.ZipFile) -> str:
    container = _read_zip_xml(archive, "META-INF/container.xml")
    rootfile = container.find(f"{{{CONTAINER_NS}}}rootfiles/{{{CONTAINER_NS}}}rootfile")
    if rootfile is None:
        raise ValueError("container.xml has no rootfile")
    return rootfile.attrib["full-path"]


def _manifest(opf: ET.Element) -> Dict[str, Dict[str, str]]:
    items = {}
    for item in opf.findall(f"{{{OPF_NS}}}manifest/{{{OPF_NS}}}item"):
        items[item.attrib["id"]] = dict(item.attrib)
    return items


def _spine(opf: ET.Element, manifest: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    result = []
    for itemref in opf.findall(f"{{{OPF_NS}}}spine/{{{OPF_NS}}}itemref"):
        item = manifest.get(itemref.attrib["idref"])
        if item:
            result.append(item)
    return result


def _ncx_points(ncx: ET.Element) -> List[Dict[str, Any]]:
    """Flatten navPoints in document order with their depth."""

    def walk(parent: ET.Element, depth: int, out: List[Dict[str, Any]]) -> None:
        for point in parent.findall(f"{{{NCX_NS}}}navPoint"):
            label = _text(point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text"))
            content = point.find(f"{{{NCX_NS}}}content")
            src = (content.attrib.get("src", "") if content is not None else "").split("#")[0]
            out.append({"title": label, "src": src, "depth": depth})
            walk(point, depth + 1, out)

    out: List[Dict[str, Any]] = []
    nav_map = ncx.find(f"{{{NCX_NS}}}navMap")
    if nav_map is not None:
        walk(nav_map, 0, out)
    return out


def _metadata_value(metadata: ET.Element, tag: str, dc: bool = True) -> str:
    namespace = DC_NS if dc else OPF_NS
    return _text(metadata.find(f"{{{namespace}}}{tag}"))


def _guess_media_type(href: str) -> str:
    guessed, _ = mimetypes.guess_type(href)
    return guessed or "application/octet-stream"


def _is_content(href: str) -> bool:
    return href.lower().endswith((".xhtml", ".html", ".htm"))


def _resolve_zip_path(opf_dir: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(opf_dir, href))


def _new_identifier(source_identifier: str, index: int) -> str:
    base = source_identifier.strip() or "urn:uuid:malazan-omnibus"
    return f"{base}#book-{index}"


def _build_opf(
    *,
    title: str,
    series: str,
    index: int,
    author: str,
    language: str,
    identifier: str,
    publisher: str,
    rights: str,
    docs: List[Dict[str, str]],
    assets: List[Dict[str, str]],
    opf_dir: str,
) -> bytes:
    ET.register_namespace("", OPF_NS)
    ET.register_namespace("dc", DC_NS)
    package = ET.Element(f"{{{OPF_NS}}}package", {
        "version": "2.0",
        "unique-identifier": "BookId",
    })
    metadata = ET.SubElement(package, f"{{{OPF_NS}}}metadata")
    ET.SubElement(metadata, f"{{{DC_NS}}}title").text = title
    ET.SubElement(metadata, f"{{{DC_NS}}}creator").text = author
    ET.SubElement(metadata, f"{{{DC_NS}}}language").text = language or "en"
    ET.SubElement(metadata, f"{{{DC_NS}}}identifier", {"id": "BookId"}).text = identifier
    if publisher:
        ET.SubElement(metadata, f"{{{DC_NS}}}publisher").text = publisher
    if rights:
        ET.SubElement(metadata, f"{{{DC_NS}}}rights").text = rights
    ET.SubElement(metadata, f"{{{OPF_NS}}}meta", {
        "name": "calibre:series",
        "content": series,
    })
    ET.SubElement(metadata, f"{{{OPF_NS}}}meta", {
        "name": "calibre:series_index",
        "content": str(index),
    })

    manifest = ET.SubElement(package, f"{{{OPF_NS}}}manifest")
    doc_ids = []
    for offset, doc in enumerate(docs):
        item_id = f"doc{offset:04d}"
        doc_ids.append(item_id)
        ET.SubElement(manifest, f"{{{OPF_NS}}}item", {
            "id": item_id,
            "href": doc["href"],
            "media-type": doc.get("media-type") or "application/xhtml+xml",
        })
    for offset, asset in enumerate(assets):
        ET.SubElement(manifest, f"{{{OPF_NS}}}item", {
            "id": f"asset{offset:04d}",
            "href": asset["href"],
            "media-type": asset.get("media-type") or _guess_media_type(asset["href"]),
        })
    ET.SubElement(manifest, f"{{{OPF_NS}}}item", {
        "id": "ncx",
        "href": "toc.ncx",
        "media-type": "application/x-dtbncx+xml",
    })

    spine = ET.SubElement(package, f"{{{OPF_NS}}}spine", {"toc": "ncx"})
    for item_id in doc_ids:
        ET.SubElement(spine, f"{{{OPF_NS}}}itemref", {"idref": item_id})

    if docs:
        guide = ET.SubElement(package, f"{{{OPF_NS}}}guide")
        ET.SubElement(guide, f"{{{OPF_NS}}}reference", {
            "type": "text",
            "title": "Start",
            "href": docs[0]["href"],
        })

    return ET.tostring(package, encoding="utf-8", xml_declaration=True)


def _build_ncx(
    *,
    title: str,
    identifier: str,
    entries: List[Tuple[str, str]],
) -> bytes:
    ET.register_namespace("", NCX_NS)
    ncx = ET.Element(f"{{{NCX_NS}}}ncx", {"version": "2005-1"})
    head = ET.SubElement(ncx, f"{{{NCX_NS}}}head")
    ET.SubElement(head, f"{{{NCX_NS}}}meta", {"name": "dtb:uid", "content": identifier})
    ET.SubElement(head, f"{{{NCX_NS}}}meta", {"name": "dtb:depth", "content": "1"})
    ET.SubElement(head, f"{{{NCX_NS}}}meta", {"name": "dtb:totalPageCount", "content": "0"})
    ET.SubElement(head, f"{{{NCX_NS}}}meta", {"name": "dtb:maxPageNumber", "content": "0"})
    doc_title = ET.SubElement(ncx, f"{{{NCX_NS}}}docTitle")
    ET.SubElement(doc_title, f"{{{NCX_NS}}}text").text = title
    nav_map = ET.SubElement(ncx, f"{{{NCX_NS}}}navMap")
    for order, (label, href) in enumerate(entries, start=1):
        point = ET.SubElement(nav_map, f"{{{NCX_NS}}}navPoint", {
            "id": f"navPoint-{order}",
            "playOrder": str(order),
        })
        nav_label = ET.SubElement(point, f"{{{NCX_NS}}}navLabel")
        ET.SubElement(nav_label, f"{{{NCX_NS}}}text").text = label
        ET.SubElement(point, f"{{{NCX_NS}}}content", {"src": href})
    return ET.tostring(ncx, encoding="utf-8", xml_declaration=True)


def split_omnibus(
    source: Path,
    out_dir: Path,
    series: str,
    author: str,
) -> List[Dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []
    with zipfile.ZipFile(source) as archive:
        opf_path = _container_opf_path(archive)
        opf_dir = posixpath.dirname(opf_path)
        opf = _read_zip_xml(archive, opf_path)
        metadata = opf.find(f"{{{OPF_NS}}}metadata")
        if metadata is None:
            raise ValueError("OPF has no metadata")
        source_title = _metadata_value(metadata, "title")
        source_author = _metadata_value(metadata, "creator") or author
        language = _metadata_value(metadata, "language") or "en"
        publisher = _metadata_value(metadata, "publisher")
        rights = _metadata_value(metadata, "rights")
        source_identifier = _metadata_value(metadata, "identifier")
        manifest = _manifest(opf)
        spine = _spine(opf, manifest)

        ncx_item = next(
            (item for item in manifest.values()
             if item.get("media-type") == "application/x-dtbncx+xml"),
            None,
        )
        if ncx_item is None:
            raise ValueError("source EPUB has no NCX")
        ncx_href = ncx_item["href"]
        ncx = _read_zip_xml(archive, _resolve_zip_path(opf_dir, ncx_href))
        points = _ncx_points(ncx)

        href_to_index = {
            item["href"].split("#")[0]: index for index, item in enumerate(spine)
        }
        labels_by_href: Dict[str, str] = {}
        for point in points:
            if point["src"] and point["src"] not in labels_by_href:
                labels_by_href[point["src"]] = point["title"]

        books: List[Dict[str, Any]] = []
        for point in points:
            match = BOOK_TITLE_RE.match(point["title"])
            if not match:
                continue
            index = int(match.group(1))
            title = _display_title(match.group(2).strip())
            start = href_to_index.get(point["src"])
            if start is None:
                raise ValueError(f"book title page not in spine: {point['src']}")
            books.append({"index": index, "title": title, "start": start})
        if not books:
            raise ValueError("no top-level BOOK N: title entries found")
        books.sort(key=lambda item: item["index"])

        after_last = [
            href_to_index[p["src"]]
            for p in points
            if p["depth"] == 0
            and p["src"] in href_to_index
            and href_to_index[p["src"]] > books[-1]["start"]
        ]
        tail_start = min(after_last) if after_last else len(spine)

        assets = []
        for name in archive.namelist():
            lower = name.lower()
            if name == "mimetype" or name.startswith("META-INF/"):
                continue
            if name in {opf_path, _resolve_zip_path(opf_dir, ncx_href)}:
                continue
            if lower.endswith((".xhtml", ".html", ".htm", ".opf", ".ncx")):
                continue
            href = posixpath.relpath(name, opf_dir)
            assets.append({"href": href, "path": name, "media-type": _guess_media_type(href)})

        container_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<container version="1.0" xmlns="{CONTAINER_NS}">\n'
            "  <rootfiles>\n"
            f'    <rootfile full-path="{opf_path}" media-type="application/oebps-package+xml"/>\n'
            "  </rootfiles>\n"
            "</container>\n"
        ).encode("utf-8")

        for position, book in enumerate(books):
            start = book["start"]
            end = books[position + 1]["start"] if position + 1 < len(books) else tail_start
            selected = [
                item for item in spine[start:end]
                if item.get("media-type") in ("application/xhtml+xml", "text/html")
            ]
            if not selected:
                continue
            identifier = _new_identifier(source_identifier, book["index"])
            doc_entries: List[Tuple[str, str]] = []
            for offset, item in enumerate(selected):
                label = labels_by_href.get(item["href"])
                if offset == 0:
                    label = f"BOOK {book['index']}: {book['title']}"
                if not label:
                    label = f"Chapter {offset + 1}"
                doc_entries.append((label, item["href"]))

            opf_bytes = _build_opf(
                title=book["title"],
                series=series,
                index=book["index"],
                author=source_author,
                language=language,
                identifier=identifier,
                publisher=publisher,
                rights=rights,
                docs=selected,
                assets=assets,
                opf_dir=opf_dir,
            )
            ncx_bytes = _build_ncx(
                title=book["title"],
                identifier=identifier,
                entries=doc_entries,
            )

            safe_title = re.sub(r'[<>:"/\\|?*]', "", book["title"]).strip().strip(".")
            filename = f"{book['index']:02d} - {safe_title}.epub"
            target = out_dir / filename
            with zipfile.ZipFile(target, "w") as out:
                out.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
                out.writestr("META-INF/container.xml", container_xml, compress_type=zipfile.ZIP_DEFLATED)
                out.writestr(opf_path, opf_bytes, compress_type=zipfile.ZIP_DEFLATED)
                out.writestr(_resolve_zip_path(opf_dir, ncx_href), ncx_bytes, compress_type=zipfile.ZIP_DEFLATED)
                for item in selected:
                    name = _resolve_zip_path(opf_dir, item["href"])
                    out.writestr(name, archive.read(name), compress_type=zipfile.ZIP_DEFLATED)
                for asset in assets:
                    out.writestr(asset["path"], archive.read(asset["path"]), compress_type=zipfile.ZIP_DEFLATED)

            issues = validate_epub_structure(str(target))
            errors = [issue.to_dict() for issue in issues if issue.severity.value in ("error", "critical")]
            result = {
                "index": book["index"],
                "title": book["title"],
                "filename": filename,
                "path": str(target),
                "bytes": target.stat().st_size,
                "documents": len(selected),
                "validation_errors": errors,
            }
            results.append(result)
            print(f"[{book['index']:02d}] {book['title']}: {len(selected)} docs, {target.stat().st_size:,} bytes, "
                  f"{'OK' if not errors else f'{len(errors)} structural errors'}", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--series", default="Malazan Book of the Fallen")
    parser.add_argument("--author", default="Steven Erikson")
    parser.add_argument("--manifest", default="")
    args = parser.parse_args()
    source = Path(args.source)
    if not source.exists():
        print(f"source not found: {source}", file=sys.stderr)
        return 1
    results = split_omnibus(source, Path(args.out_dir), args.series, args.author)
    manifest_path = Path(args.manifest) if args.manifest else Path(args.out_dir) / "split-manifest.json"
    manifest_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {manifest_path}", flush=True)
    return 0 if all(not item["validation_errors"] for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
