"""Read-only EPUB inspection and safe metadata rewriting.

The functions here never modify the source EPUB. ``update_opf_metadata`` writes
a new file and leaves the input untouched.
"""
from __future__ import annotations

import os
import posixpath
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from .models import Severity, ValidationIssue

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"

NS = {"opf": OPF_NS, "dc": DC_NS, "ncx": NCX_NS, "xhtml": XHTML_NS, "epub": EPUB_NS}

_WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019\-][^\W\d_]+)*", re.UNICODE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip = 0
        self.links: List[str] = []
        self.images: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "br":
            self.parts.append("\n")
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "tr", "section"):
            self.parts.append("\n\n")
        if tag == "a" and attrs_dict.get("href"):
            self.links.append(attrs_dict["href"] or "")
        if tag == "img" and attrs_dict.get("src"):
            self.images.append(attrs_dict["src"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "tr", "section"):
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        blocks = []
        for block in re.split(r"\n\s*\n", raw):
            lines = [re.sub(r"[ \t]+", " ", line).strip() for line in block.splitlines()]
            clean = "\n".join(line for line in lines if line).strip()
            if clean:
                blocks.append(clean)
        return "\n\n".join(blocks)


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def extract_text_from_xhtml(raw: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(raw)
    except Exception:
        # HTMLParser is permissive; a malformed document still yields the text
        # it managed to read before the failure.
        pass
    return parser.text()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_child(parent: ET.Element, local_name: str) -> Optional[ET.Element]:
    for child in parent:
        if _local_name(child.tag) == local_name:
            return child
    return None


def _find_children(parent: ET.Element, local_name: str) -> List[ET.Element]:
    return [child for child in parent if _local_name(child.tag) == local_name]


def _read_container(zf: zipfile.ZipFile) -> str:
    try:
        root = ET.fromstring(zf.read("META-INF/container.xml"))
    except KeyError as exc:
        raise ValueError("META-INF/container.xml is missing") from exc
    for rootfile in root.iter():
        if _local_name(rootfile.tag) == "rootfile" and rootfile.attrib.get("full-path"):
            return rootfile.attrib["full-path"]
    raise ValueError("container.xml has no rootfile")


def _read_opf(zf: zipfile.ZipFile, opf_path: str) -> ET.Element:
    return ET.fromstring(zf.read(opf_path))


def _manifest_items(opf: ET.Element) -> Dict[str, Dict[str, str]]:
    manifest = None
    for child in opf:
        if _local_name(child.tag) == "manifest":
            manifest = child
            break
    if manifest is None:
        return {}
    items: Dict[str, Dict[str, str]] = {}
    for item in manifest:
        if _local_name(item.tag) != "item":
            continue
        item_id = item.attrib.get("id")
        if item_id:
            items[item_id] = dict(item.attrib)
    return items


def _spine_items(opf: ET.Element, manifest: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    spine = None
    for child in opf:
        if _local_name(child.tag) == "spine":
            spine = child
            break
    if spine is None:
        return []
    result = []
    for itemref in spine:
        if _local_name(itemref.tag) != "itemref":
            continue
        idref = itemref.attrib.get("idref")
        if idref and idref in manifest:
            result.append(manifest[idref])
    return result


def _resolve_href(base_dir: str, href: str) -> str:
    clean = unquote(urlsplit(href).path)
    if not clean:
        return ""
    joined = posixpath.normpath(posixpath.join(base_dir, clean))
    return joined.lstrip("/")


def _metadata(opf: ET.Element) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    meta_values: Dict[str, str] = {}
    for child in opf:
        if _local_name(child.tag) != "metadata":
            continue
        for el in child:
            name = _local_name(el.tag)
            text = (el.text or "").strip()
            if name in {"title", "creator", "language", "identifier", "publisher", "date"} and text:
                metadata.setdefault(name, text)
            if name == "meta":
                prop = el.attrib.get("property") or el.attrib.get("name")
                if prop and text:
                    meta_values[prop] = text
    metadata["meta"] = meta_values
    return metadata


def _parse_nav(zf: zipfile.ZipFile, nav_href: str) -> List[Dict[str, str]]:
    try:
        raw = zf.read(nav_href)
        root = ET.fromstring(raw)
    except Exception:
        return []
    entries: List[Dict[str, str]] = []
    for nav in root.iter():
        if _local_name(nav.tag) != "nav":
            continue
        nav_type = nav.attrib.get(f"{{{EPUB_NS}}}type", "")
        if nav_type and nav_type != "toc":
            continue
        for anchor in nav.iter():
            if _local_name(anchor.tag) != "a":
                continue
            href = anchor.attrib.get("href", "")
            text = " ".join("".join(anchor.itertext()).split())
            if href and text:
                entries.append({"title": text, "href": href})
    if entries:
        return entries
    # Some EPUB3 files omit epub:type; fall back to anchors inside nav.
    for anchor in root.iter():
        if _local_name(anchor.tag) == "a":
            href = anchor.attrib.get("href", "")
            text = " ".join("".join(anchor.itertext()).split())
            if href and text:
                entries.append({"title": text, "href": href})
    return entries


def _parse_ncx(zf: zipfile.ZipFile, ncx_href: str) -> List[Dict[str, str]]:
    try:
        root = ET.fromstring(zf.read(ncx_href))
    except Exception:
        return []
    entries: List[Dict[str, str]] = []
    for nav_point in root.iter():
        if _local_name(nav_point.tag) != "navPoint":
            continue
        label = ""
        src = ""
        for child in nav_point:
            name = _local_name(child.tag)
            if name == "navLabel":
                text_el = _find_child(child, "text")
                if text_el is not None and text_el.text:
                    label = " ".join(text_el.text.split())
            elif name == "content":
                src = child.attrib.get("src", "")
        if label:
            entries.append({"title": label, "href": src})
    return entries


@dataclass
class EpubInfo:
    path: str
    title: str = ""
    creator: str = ""
    language: str = ""
    identifier: str = ""
    opf_path: str = ""
    opf_dir: str = ""
    toc: List[Dict[str, str]] = field(default_factory=list)
    word_count: int = 0
    document_count: int = 0
    text: str = ""
    issues: List[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "creator": self.creator,
            "language": self.language,
            "identifier": self.identifier,
            "opf_path": self.opf_path,
            "opf_dir": self.opf_dir,
            "toc": self.toc,
            "word_count": self.word_count,
            "document_count": self.document_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def read_epub(path: str, include_text: bool = True) -> EpubInfo:
    """Inspect an EPUB without writing to it."""
    info = EpubInfo(path=os.path.abspath(path))
    if not os.path.exists(path):
        info.issues.append(ValidationIssue("epub.missing", "EPUB file not found", Severity.CRITICAL, path))
        return info

    try:
        with zipfile.ZipFile(path) as zf:
            info.opf_path = _read_container(zf)
            info.opf_dir = posixpath.dirname(info.opf_path)
            opf = _read_opf(zf, info.opf_path)
            metadata = _metadata(opf)
            info.title = metadata.get("title", "")
            info.creator = metadata.get("creator", "")
            info.language = metadata.get("language", "")
            info.identifier = metadata.get("identifier", "")
            manifest = _manifest_items(opf)
            spine = _spine_items(opf, manifest)
            info.document_count = len(spine)

            nav_href = ""
            ncx_href = ""
            for item in manifest.values():
                props = (item.get("properties") or "").split()
                if "nav" in props:
                    nav_href = _resolve_href(info.opf_dir, item.get("href", ""))
                if item.get("media-type") == "application/x-dtbncx+xml":
                    ncx_href = _resolve_href(info.opf_dir, item.get("href", ""))
            if nav_href:
                info.toc = _parse_nav(zf, nav_href)
            if not info.toc and ncx_href:
                info.toc = _parse_ncx(zf, ncx_href)

            texts: List[str] = []
            for item in spine:
                href = item.get("href", "")
                if item.get("media-type") not in ("application/xhtml+xml", "text/html"):
                    continue
                full = _resolve_href(info.opf_dir, href)
                try:
                    raw = zf.read(full).decode("utf-8", "replace")
                except KeyError:
                    info.issues.append(ValidationIssue("epub.spine_missing", f"Spine document missing: {full}", Severity.ERROR, full))
                    continue
                text = extract_text_from_xhtml(raw)
                texts.append(text)
            if include_text:
                info.text = "\n\n".join(texts)
            info.word_count = sum(count_words(text) for text in texts)
    except Exception as exc:
        info.issues.append(ValidationIssue("epub.unreadable", str(exc), Severity.CRITICAL, path))
    return info


def iter_spine_documents(path: str) -> Iterable[Dict[str, Any]]:
    """Yield spine documents with href, absolute path, raw XHTML and text."""
    with zipfile.ZipFile(path) as zf:
        opf_path = _read_container(zf)
        opf_dir = posixpath.dirname(opf_path)
        opf = _read_opf(zf, opf_path)
        manifest = _manifest_items(opf)
        for item in _spine_items(opf, manifest):
            if item.get("media-type") not in ("application/xhtml+xml", "text/html"):
                continue
            href = item.get("href", "")
            full = _resolve_href(opf_dir, href)
            try:
                raw = zf.read(full).decode("utf-8", "replace")
            except KeyError:
                continue
            yield {
                "href": href,
                "path": full,
                "raw": raw,
                "text": extract_text_from_xhtml(raw),
            }


def _try_parse_xml(raw: bytes) -> Optional[ET.Element]:
    try:
        return ET.fromstring(raw)
    except Exception:
        return None


def validate_epub_structure(path: str) -> List[ValidationIssue]:
    """Deterministic structural validation.

    This is not a replacement for EPUBCheck; it catches the failures most
    likely to make a translated book unreadable (bad ZIP, broken OPF/spine,
    missing resources, malformed XHTML, zip-slip entries).
    """
    issues: List[ValidationIssue] = []
    if not os.path.exists(path):
        return [ValidationIssue("epub.missing", "EPUB file not found", Severity.CRITICAL, path)]

    try:
        zf = zipfile.ZipFile(path)
    except Exception as exc:
        return [ValidationIssue("epub.bad_zip", str(exc), Severity.CRITICAL, path)]

    with zf:
        names = zf.namelist()
        if not names:
            issues.append(ValidationIssue("epub.empty", "EPUB has no entries", Severity.CRITICAL, path))
            return issues
        if names[0] != "mimetype":
            issues.append(ValidationIssue("epub.mimetype_order", "mimetype is not the first ZIP entry", Severity.ERROR, path))
        try:
            mimetype_info = zf.getinfo("mimetype")
            if mimetype_info.compress_type != zipfile.ZIP_STORED:
                issues.append(ValidationIssue("epub.mimetype_compressed", "mimetype must be stored uncompressed", Severity.ERROR, path))
            if zf.read("mimetype").strip() != b"application/epub+zip":
                issues.append(ValidationIssue("epub.mimetype_value", "mimetype is not application/epub+zip", Severity.ERROR, path))
        except KeyError:
            issues.append(ValidationIssue("epub.mimetype_missing", "mimetype entry is missing", Severity.CRITICAL, path))

        seen = set()
        for name in names:
            if name in seen:
                issues.append(ValidationIssue("epub.duplicate_entry", f"Duplicate ZIP entry: {name}", Severity.ERROR, name))
            seen.add(name)
            normalized = posixpath.normpath(name)
            if normalized.startswith("../") or normalized.startswith("/") or ".." in normalized.split("/"):
                issues.append(ValidationIssue("epub.zip_slip", f"Unsafe ZIP entry: {name}", Severity.CRITICAL, name))

        try:
            opf_path = _read_container(zf)
        except Exception as exc:
            issues.append(ValidationIssue("epub.container", str(exc), Severity.CRITICAL, path))
            return issues
        opf_dir = posixpath.dirname(opf_path)
        try:
            opf = _read_opf(zf, opf_path)
        except Exception as exc:
            issues.append(ValidationIssue("epub.opf_parse", str(exc), Severity.CRITICAL, opf_path))
            return issues

        manifest = _manifest_items(opf)
        if not manifest:
            issues.append(ValidationIssue("epub.manifest_empty", "OPF manifest is empty", Severity.CRITICAL, opf_path))
        for item in manifest.values():
            href = item.get("href", "")
            if not href:
                continue
            full = _resolve_href(opf_dir, href)
            if full and full not in names:
                issues.append(ValidationIssue("epub.manifest_missing", f"Manifest item missing from ZIP: {full}", Severity.ERROR, opf_path))

        spine = _spine_items(opf, manifest)
        if not spine:
            issues.append(ValidationIssue("epub.spine_empty", "OPF spine is empty", Severity.CRITICAL, opf_path))

        for item in spine:
            href = item.get("href", "")
            full = _resolve_href(opf_dir, href)
            if full not in names:
                continue
            if item.get("media-type") in ("application/xhtml+xml", "text/html"):
                root = _try_parse_xml(zf.read(full))
                if root is None:
                    issues.append(ValidationIssue("epub.xhtml_parse", f"XHTML is not well-formed: {full}", Severity.ERROR, full))
                    continue
                for element in root.iter():
                    tag = _local_name(element.tag)
                    if tag not in {"a", "img", "link", "script"}:
                        continue
                    attr = "href" if tag in {"a", "link"} else "src"
                    target = element.attrib.get(attr, "")
                    if not target or target.startswith(("http://", "https://", "mailto:", "tel:", "data:", "#")):
                        continue
                    resolved = _resolve_href(posixpath.dirname(full), target)
                    if resolved and resolved not in names:
                        issues.append(ValidationIssue("epub.link_missing", f"Internal resource missing: {target}", Severity.WARNING, full))

        nav_href = ""
        ncx_href = ""
        for item in manifest.values():
            props = (item.get("properties") or "").split()
            if "nav" in props:
                nav_href = _resolve_href(opf_dir, item.get("href", ""))
            if item.get("media-type") == "application/x-dtbncx+xml":
                ncx_href = _resolve_href(opf_dir, item.get("href", ""))
        if nav_href:
            if _try_parse_xml(zf.read(nav_href)) is None:
                issues.append(ValidationIssue("epub.nav_parse", "Navigation document is not well-formed", Severity.ERROR, nav_href))
        if ncx_href:
            if _try_parse_xml(zf.read(ncx_href)) is None:
                issues.append(ValidationIssue("epub.ncx_parse", "NCX is not well-formed", Severity.ERROR, ncx_href))

    return issues


def _set_dc_text(metadata: ET.Element, tag: str, value: str, dc_ns: str = DC_NS) -> None:
    for el in metadata:
        if _local_name(el.tag) == tag:
            el.text = value
            return
    el = ET.SubElement(metadata, f"{{{dc_ns}}}{tag}")
    el.text = value


def _set_meta(
    metadata: ET.Element,
    *,
    name: str = "",
    property_name: str = "",
    value: str,
    refines: str = "",
    element_id: str = "",
    scheme: str = "",
) -> None:
    # EPUB 2-style Calibre metadata uses name/content; EPUB 3 properties use
    # property/refines with text content.  Mixing the two shapes makes
    # EPUBCheck reject the OPF with "meta missing required attribute content".
    use_content = bool(name) and not property_name
    for el in metadata:
        if _local_name(el.tag) != "meta":
            continue
        if refines and el.attrib.get("refines") != refines:
            continue
        if name and el.attrib.get("name") == name:
            if use_content:
                el.set("content", value)
                el.text = None
            else:
                el.text = value
                el.attrib.pop("content", None)
            if element_id:
                el.set("id", element_id)
            if scheme:
                el.set("scheme", scheme)
            return
        if property_name and el.attrib.get("property") == property_name:
            el.text = value
            el.attrib.pop("content", None)
            if element_id:
                el.set("id", element_id)
            if scheme:
                el.set("scheme", scheme)
            return
    attrs = {}
    if name:
        attrs["name"] = name
    if property_name:
        attrs["property"] = property_name
    if refines:
        attrs["refines"] = refines
    if element_id:
        attrs["id"] = element_id
    if scheme:
        attrs["scheme"] = scheme
    if use_content:
        attrs["content"] = value
    el = ET.SubElement(metadata, f"{{{OPF_NS}}}meta", attrs)
    if not use_content:
        el.text = value


def _set_subjects(metadata: ET.Element, subjects: list[str], dc_ns: str = DC_NS) -> None:
    for el in list(metadata):
        if _local_name(el.tag) == "subject":
            metadata.remove(el)
    for subject in subjects:
        if not str(subject).strip():
            continue
        el = ET.SubElement(metadata, f"{{{dc_ns}}}subject")
        el.text = str(subject).strip()


def _set_translator(
    metadata: ET.Element, translator: str, dc_ns: str = DC_NS, *, epub2: bool = False
) -> None:
    for el in list(metadata):
        if _local_name(el.tag) == "contributor" and el.attrib.get("id") == "tbl-translator":
            metadata.remove(el)
    for el in list(metadata):
        if _local_name(el.tag) == "meta" and el.attrib.get("refines") == "#tbl-translator":
            metadata.remove(el)
    contributor = ET.SubElement(
        metadata, f"{{{dc_ns}}}contributor", {"id": "tbl-translator"}
    )
    contributor.text = translator
    if epub2:
        contributor.set(f"{{{OPF_NS}}}role", "trl")
        return
    _set_meta(
        metadata,
        property_name="role",
        value="trl",
        refines="#tbl-translator",
        scheme="marc:relators",
    )



def update_opf_metadata(
    source_path: str,
    output_path: str,
    *,
    title: Optional[str] = None,
    language: Optional[str] = None,
    identifier: Optional[str] = None,
    series: Optional[str] = None,
    series_index: Optional[float] = None,
    subjects: Optional[List[str]] = None,
    description: Optional[str] = None,
    translator: str = "",
    title_sort: Optional[str] = None,
    author_sort: Optional[str] = None,
) -> str:
    """Write a copy of ``source_path`` with selected OPF metadata updated.

    The source file is never modified. The output is written atomically.
    """
    source_path = os.path.abspath(source_path)
    output_path = os.path.abspath(output_path)
    out_dir = os.path.dirname(output_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    with zipfile.ZipFile(source_path, "r") as zin:
        opf_path = _read_container(zin)
        opf_dir = posixpath.dirname(opf_path)
        opf = _read_opf(zin, opf_path)
        metadata = None
        for child in opf:
            if _local_name(child.tag) == "metadata":
                metadata = child
                break
        if metadata is None:
            metadata = ET.SubElement(opf, f"{{{OPF_NS}}}metadata")
        epub2 = str(opf.attrib.get("version", "2.0")).strip().startswith("2")
        if title is not None:
            _set_dc_text(metadata, "title", title)
        if language is not None:
            _set_dc_text(metadata, "language", language)
        if identifier is not None:
            _set_dc_text(metadata, "identifier", identifier)
        if description is not None:
            _set_dc_text(metadata, "description", description)
        if subjects:
            _set_subjects(metadata, subjects)
        if translator:
            _set_translator(metadata, translator, epub2=epub2)
        if title_sort:
            _set_meta(metadata, name="calibre:title_sort", value=title_sort)
        if author_sort:
            _set_meta(metadata, name="calibre:author_sort", value=author_sort)
        if series is not None:
            if not epub2:
                _set_meta(
                    metadata,
                    property_name="belongs-to-collection",
                    value=series,
                    element_id="tbl-series",
                )
                _set_meta(
                    metadata,
                    property_name="collection-type",
                    value="series",
                    refines="#tbl-series",
                )
            _set_meta(metadata, name="calibre:series", value=series)
        if series_index is not None:
            value = f"{series_index:g}"
            if not epub2:
                _set_meta(
                    metadata,
                    property_name="group-position",
                    value=value,
                    refines="#tbl-series",
                )
            _set_meta(metadata, name="calibre:series_index", value=value)

        new_opf = ET.tostring(opf, encoding="utf-8", xml_declaration=True)

        fd, temp_path = tempfile.mkstemp(prefix=".epub-meta-", suffix=".epub", dir=out_dir)
        os.close(fd)
        try:
            with zipfile.ZipFile(temp_path, "w") as zout:
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    if info.filename == opf_path:
                        data = new_opf
                    zout.writestr(info, data)
            os.replace(temp_path, output_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    return output_path
