"""Split a well-structured omnibus EPUB into one EPUB per contained book.

Two boundary modes are supported:

* **NCX mode (legacy)** — top-level NCX entries labelled ``BOOK 1: ...``.
* **Spine-prefix mode** — consecutive spine documents whose file name matches a
  regex with a named ``n`` group, e.g. ``_Book(?P<n>\\d+)_``. This handles
  omnibus editions that expose each novel as a ``BookN_*`` run of files instead
  of a ``BOOK N:`` label.

The splitter reuses the source spine, copies only the assets the selected
documents need (optional), wires a per-volume cover, and writes a fresh EPUB 2
package per book. It never writes into the source library; pass an explicit
``--out-dir``.

Usage (legacy):
    python scripts/split_omnibus.py \
        --source "...The Complete Malazan Book....epub" \
        --out-dir data/calibre/malazan-split \
        --series "Malazan Book of the Fallen" \
        --author "Steven Erikson"

Usage (spine-prefix, per-volume metadata and cover):
    python scripts/split_omnibus.py \
        --source data/calibre/prepared/the-rain-wild-chronicles.epub \
        --out-dir translated_files \
        --spine-prefix-regex "_Book(?P<n>\\d+)_" \
        --titles-json data/calibre/rain-wild-pt-titles.json \
        --language pt-BR \
        --description-mode translation \
        --subjects "Realm of the Elderlings,Fiction,Speculative Fiction,Fantasy,Epic Fantasy,High Fantasy" \
        --filename-template "{title} (pt-BR).refined.epub" \
        --prune-assets \
        --cover-image-regex "_Book{n}_cover\\." \
        --cover-page-regex "_Book{n}_Cover\\." \
        --epubcheck
"""
from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import posixpath
import re
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.literary.epub import update_opf_metadata, validate_epub_structure  # noqa: E402
from src.literary.metadata import author_sort, translation_description  # noqa: E402

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

BOOK_TITLE_RE = re.compile(r"^BOOK\s+(\d+)\s*:\s*(.+)$", re.IGNORECASE)
SMALL_TITLE_WORDS = {"of", "the", "and", "in", "a", "an", "to", "for", "on", "at", "by", "with", "from"}

_REFERENCE_RE = re.compile(
    r"""(?:src|href)\s*=\s*["']([^"']+)["']|url\(\s*['"]?([^'")]+)""",
    re.IGNORECASE,
)
_SKIP_REFERENCE_PREFIXES = ("#", "data:", "http:", "https:", "mailto:", "tel:", "javascript:")


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
    base = source_identifier.strip() or "urn:uuid:omnibus"
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'{base}#book-{index}')}"


_HTML_TAG_RE = re.compile(r"<html\b[^>]*>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title\b[^>]*>.*?</title>", re.IGNORECASE | re.DOTALL)


def _localize_document(data: bytes, *, language: str, title: str) -> bytes:
    """Align the document language and title with the split volume."""
    text = data.decode("utf-8")

    def fix_html_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        for attribute in ("xml:lang", "lang"):
            pattern = re.compile(
                rf"""(?<=\s){re.escape(attribute)}\s*=\s*["'][^"']*["']""",
                re.IGNORECASE,
            )
            if pattern.search(tag):
                tag = pattern.sub(f'{attribute}="{language}"', tag, count=1)
            else:
                tag = tag[:-1] + f' {attribute}="{language}">'
        return tag

    text = _HTML_TAG_RE.sub(fix_html_tag, text, count=1)
    text = _TITLE_RE.sub(lambda match: f"<title>{html.escape(title)}</title>", text, count=1)
    return text.encode("utf-8")


def _books_from_ncx(
    points: List[Dict[str, Any]], href_to_index: Dict[str, int]
) -> Tuple[List[Dict[str, Any]], int]:
    """Legacy boundary detection: NCX labels shaped as ``BOOK N: Title``."""
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
        books.append({"index": index, "title": title, "source_title": title, "start": start})
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
    tail_start = min(after_last) if after_last else len(href_to_index)
    return books, tail_start


def _books_from_spine(
    spine: List[Dict[str, str]],
    pattern: str,
    labels_by_href: Dict[str, str],
    titles: Dict[int, str],
) -> List[Dict[str, Any]]:
    """Detect volumes as consecutive spine runs matching ``pattern``."""
    compiled = re.compile(pattern)
    runs: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for position, item in enumerate(spine):
        match = compiled.search(item["href"])
        if not match:
            current = None
            continue
        raw_index = match.groupdict().get("n")
        if raw_index is None:
            raise ValueError("spine-prefix regex must expose a named group 'n'")
        index = int(raw_index)
        if current is None or current["index"] != index:
            current = {"index": index, "start": position, "end": position + 1}
            runs.append(current)
        else:
            current["end"] = position + 1

    seen: set[int] = set()
    books: List[Dict[str, Any]] = []
    for run in runs:
        index = run["index"]
        if index in seen:
            raise ValueError(f"volume {index} appears in more than one spine run")
        seen.add(index)
        first_href = spine[run["start"]]["href"]
        source_title = labels_by_href.get(first_href, "")
        title = titles.get(index) or source_title or f"Book {index}"
        books.append(
            {
                "index": index,
                "title": title,
                "source_title": source_title,
                "start": run["start"],
                "end": run["end"],
            }
        )
    if not books:
        raise ValueError(f"no spine documents match {pattern!r}")
    books.sort(key=lambda item: item["index"])
    return books


def _extract_references(markup: str) -> List[str]:
    references: List[str] = []
    for match in _REFERENCE_RE.finditer(markup):
        reference = (match.group(1) or match.group(2) or "").strip()
        if not reference or reference.lower().startswith(_SKIP_REFERENCE_PREFIXES):
            continue
        references.append(reference.split("#", 1)[0].split("?", 1)[0])
    return references


def _referenced_asset_paths(
    archive: zipfile.ZipFile,
    document_paths: List[str],
    asset_paths: List[str],
) -> set[str]:
    """Transitively collect the assets referenced by the selected documents."""
    available = set(asset_paths)
    kept: set[str] = set()
    pending = list(document_paths)
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            data = archive.read(current).decode("utf-8", "replace")
        except KeyError:
            continue
        base = posixpath.dirname(current)
        for reference in _extract_references(data):
            target = posixpath.normpath(posixpath.join(base, reference))
            if target in available and target not in kept:
                kept.add(target)
                pending.append(target)
    return kept


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
    cover_id: str = "",
    cover_href: str = "",
    toc_href: str = "",
    text_href: str = "",
    ncx_href: str = "toc.ncx",
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
    if cover_id:
        ET.SubElement(metadata, f"{{{OPF_NS}}}meta", {
            "name": "cover",
            "content": cover_id,
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
        "href": ncx_href,
        "media-type": "application/x-dtbncx+xml",
    })

    spine = ET.SubElement(package, f"{{{OPF_NS}}}spine", {"toc": "ncx"})
    for item_id in doc_ids:
        ET.SubElement(spine, f"{{{OPF_NS}}}itemref", {"idref": item_id})

    if docs:
        guide = ET.SubElement(package, f"{{{OPF_NS}}}guide")
        if cover_href:
            ET.SubElement(guide, f"{{{OPF_NS}}}reference", {
                "type": "cover",
                "title": "Cover",
                "href": cover_href,
            })
        if toc_href:
            ET.SubElement(guide, f"{{{OPF_NS}}}reference", {
                "type": "toc",
                "title": "Contents",
                "href": toc_href,
            })
        ET.SubElement(guide, f"{{{OPF_NS}}}reference", {
            "type": "text",
            "title": "Start",
            "href": text_href or docs[0]["href"],
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


def _matches(pattern: str, index: int, value: str) -> bool:
    if not pattern:
        return False
    return bool(re.search(pattern.replace("{n}", str(index)), value))


def split_omnibus(
    source: Path,
    out_dir: Path,
    series: str,
    author: str,
    *,
    spine_prefix_regex: str = "",
    titles: Optional[Dict[int, str]] = None,
    language: str = "",
    description_template: str = "",
    subjects: Optional[List[str]] = None,
    translator: str = "",
    filename_template: str = "{index:02d} - {title}.epub",
    prune_assets: bool = False,
    cover_image_regex: str = "",
    cover_page_regex: str = "",
    strict_ncx_labels: bool = False,
    epubcheck_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
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
        source_author = _metadata_value(metadata, "creator") or author
        source_language = _metadata_value(metadata, "language") or "en"
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

        if spine_prefix_regex:
            books = _books_from_spine(spine, spine_prefix_regex, labels_by_href, titles or {})
            tail_start = len(spine)
        else:
            books, tail_start = _books_from_ncx(points, href_to_index)

        all_assets: List[Dict[str, Any]] = []
        for name in archive.namelist():
            lower = name.lower()
            if name == "mimetype" or name.startswith("META-INF/"):
                continue
            if name in {opf_path, _resolve_zip_path(opf_dir, ncx_href)}:
                continue
            if lower.endswith((".xhtml", ".html", ".htm", ".opf", ".ncx")):
                continue
            href = posixpath.relpath(name, opf_dir)
            all_assets.append({"href": href, "path": name, "media-type": _guess_media_type(href)})

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
            end = book.get("end") or (
                books[position + 1]["start"] if position + 1 < len(books) else tail_start
            )
            selected = [
                item for item in spine[start:end]
                if item.get("media-type") in ("application/xhtml+xml", "text/html")
            ]
            if not selected:
                continue
            identifier = _new_identifier(source_identifier, book["index"])
            document_paths = [_resolve_zip_path(opf_dir, item["href"]) for item in selected]

            if prune_assets:
                kept_paths = _referenced_asset_paths(
                    archive, document_paths, [asset["path"] for asset in all_assets]
                )
                assets = [asset for asset in all_assets if asset["path"] in kept_paths]
            else:
                assets = list(all_assets)

            cover_asset = next(
                (
                    asset for asset in assets
                    if _matches(cover_image_regex, book["index"], asset["path"])
                ),
                None,
            )
            cover_href = ""
            cover_page_href = ""
            if cover_page_regex:
                cover_page = next(
                    (
                        item for item in selected
                        if _matches(cover_page_regex, book["index"], item["href"])
                    ),
                    None,
                )
                if cover_page is not None:
                    cover_page_href = cover_page["href"]

            toc_href = ""
            for item in selected:
                if re.search(r"contents", posixpath.basename(item["href"]), re.IGNORECASE):
                    toc_href = item["href"]
                    break

            text_href = ""
            cover_position = next(
                (offset for offset, item in enumerate(selected) if item["href"] == cover_page_href),
                -1,
            )
            for offset, item in enumerate(selected):
                if offset != cover_position:
                    text_href = item["href"]
                    break

            doc_entries: List[Tuple[str, str]] = []
            for offset, item in enumerate(selected):
                label = labels_by_href.get(item["href"])
                if offset == 0:
                    label = (
                        book["title"]
                        if spine_prefix_regex
                        else f"BOOK {book['index']}: {book['title']}"
                    )
                if not label:
                    if strict_ncx_labels:
                        continue
                    label = f"Chapter {offset + 1}"
                doc_entries.append((label, item["href"]))

            cover_id = ""
            if cover_asset is not None:
                cover_id = f"asset{assets.index(cover_asset):04d}"
                cover_href = cover_page_href or cover_asset["href"]

            opf_bytes = _build_opf(
                title=book["title"],
                series=series,
                index=book["index"],
                author=source_author,
                language=language or source_language,
                identifier=identifier,
                publisher=publisher,
                rights=rights,
                docs=selected,
                assets=assets,
                cover_id=cover_id,
                cover_href=cover_href,
                toc_href=toc_href,
                text_href=text_href,
                ncx_href=posixpath.relpath(
                    _resolve_zip_path(opf_dir, ncx_href), opf_dir
                ),
            )
            ncx_bytes = _build_ncx(
                title=book["title"],
                identifier=identifier,
                entries=doc_entries,
            )

            safe_title = re.sub(r'[<>:"/\\|?*]', "", book["title"]).strip().strip(".")
            safe_source_title = re.sub(
                r'[<>:"/\\|?*]', "", book.get("source_title") or book["title"]
            ).strip().strip(".")
            filename = filename_template.format(
                index=book["index"], title=safe_title, source_title=safe_source_title
            )
            target = out_dir / filename
            with zipfile.ZipFile(target, "w") as out:
                out.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
                out.writestr("META-INF/container.xml", container_xml, compress_type=zipfile.ZIP_DEFLATED)
                out.writestr(opf_path, opf_bytes, compress_type=zipfile.ZIP_DEFLATED)
                out.writestr(_resolve_zip_path(opf_dir, ncx_href), ncx_bytes, compress_type=zipfile.ZIP_DEFLATED)
                for item in selected:
                    name = _resolve_zip_path(opf_dir, item["href"])
                    payload = archive.read(name)
                    if language:
                        payload = _localize_document(
                            payload, language=language, title=book["title"]
                        )
                    out.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED)
                for asset in assets:
                    out.writestr(asset["path"], archive.read(asset["path"]), compress_type=zipfile.ZIP_DEFLATED)

            if description_template or subjects or translator or language:
                description = ""
                if description_template:
                    description = description_template.replace("{title}", book["title"])
                fd, tmp_name = tempfile.mkstemp(prefix=".split-meta-", suffix=".epub", dir=str(out_dir))
                os.close(fd)
                staged = Path(tmp_name)
                try:
                    update_opf_metadata(
                        str(target),
                        str(staged),
                        title=book["title"],
                        language=language or None,
                        identifier=identifier,
                        series=series or None,
                        series_index=book["index"],
                        subjects=subjects or None,
                        description=description or None,
                        translator=translator or "",
                        title_sort=book["title"],
                        author_sort=author_sort(source_author),
                    )
                    os.replace(staged, target)
                finally:
                    if staged.exists():
                        staged.unlink()

            issues = validate_epub_structure(str(target))
            errors = [issue.to_dict() for issue in issues if issue.severity.value in ("error", "critical")]
            epubcheck: Dict[str, Any] = {}
            if epubcheck_fn is not None:
                epubcheck = epubcheck_fn(target.resolve())
                if (epubcheck.get("errors") or 0) or epubcheck.get("returncode"):
                    errors.append({"code": "epubcheck", **epubcheck})
            result = {
                "index": book["index"],
                "title": book["title"],
                "filename": filename,
                "path": str(target),
                "bytes": target.stat().st_size,
                "documents": len(selected),
                "assets": len(assets),
                "cover": cover_href,
                "validation_errors": errors,
                "epubcheck": epubcheck,
            }
            results.append(result)
            print(f"[{book['index']:02d}] {book['title']}: {len(selected)} docs, "
                  f"{len(assets)} assets, {target.stat().st_size:,} bytes, "
                  f"{'OK' if not errors else f'{len(errors)} structural errors'}", flush=True)
    return results


def _load_titles(raw: str) -> Dict[int, str]:
    if not raw:
        return {}
    path = Path(raw)
    if not path.is_file():
        raise SystemExit(f"titles file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(key): str(value) for key, value in data.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--series", default="Malazan Book of the Fallen")
    parser.add_argument("--author", default="Steven Erikson")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--spine-prefix-regex", default="", help="e.g. '_Book(?P<n>\\d+)_'")
    parser.add_argument("--titles-json", default="", help="JSON object {index: title}")
    parser.add_argument("--language", default="", help="Target dc:language (default: source language)")
    parser.add_argument(
        "--description-mode",
        choices=("none", "translation"),
        default="none",
        help="'translation' writes the Scriptorium edition notice for each volume",
    )
    parser.add_argument("--subjects", default="", help="Comma-separated dc:subject values")
    parser.add_argument("--translator", default="")
    parser.add_argument("--filename-template", default="{index:02d} - {title}.epub")
    parser.add_argument("--prune-assets", action="store_true")
    parser.add_argument("--cover-image-regex", default="")
    parser.add_argument("--cover-page-regex", default="")
    parser.add_argument("--strict-ncx-labels", action="store_true")
    parser.add_argument("--epubcheck", action="store_true")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"source not found: {source}", file=sys.stderr)
        return 1

    description_template = ""
    if args.description_mode == "translation":
        description_template = translation_description("{title}")

    epubcheck_fn = None
    if args.epubcheck:
        from src.literary.queue_runner import _epubcheck

        epubcheck_fn = _epubcheck

    subjects = [item.strip() for item in args.subjects.split(",") if item.strip()]

    results = split_omnibus(
        source,
        Path(args.out_dir),
        args.series,
        args.author,
        spine_prefix_regex=args.spine_prefix_regex,
        titles=_load_titles(args.titles_json),
        language=args.language,
        description_template=description_template,
        subjects=subjects,
        translator=args.translator,
        filename_template=args.filename_template,
        prune_assets=args.prune_assets,
        cover_image_regex=args.cover_image_regex,
        cover_page_regex=args.cover_page_regex,
        strict_ncx_labels=args.strict_ncx_labels,
        epubcheck_fn=epubcheck_fn,
    )
    manifest_path = Path(args.manifest) if args.manifest else Path(args.out_dir) / "split-manifest.json"
    manifest_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {manifest_path}", flush=True)
    return 0 if all(not item["validation_errors"] for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
