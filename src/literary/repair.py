"""Safe, deterministic repairs for EPUB content that is valid XHTML but wrong.

The first repair targets dropcap spans. The source pattern is
``<span class="dropcap">A</span>lice``; translation models sometimes keep the
source letter in front of a translated word (``A`` + ``Uma``) or put the whole
word inside the span (``estudos``). Both are silent content corruption, not
layout issues. The repair only acts when the next word makes the intended
result unambiguous; anything else is left for review.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Tuple

_DROPCAP_RE = re.compile(
    r'(<span[^>]*class="[^"]*\bdropcap\b[^"]*"[^>]*>)(.*?)(</span>)(.{0,200})',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_BODY_DOC_ROLE_RE = re.compile(
    r'(<body\b[^>]*?)\s+role=(?:"doc-[^"]*"|\'doc-[^\']*\')',
    re.IGNORECASE,
)


@dataclass
class DropcapRepair:
    original: str
    repaired: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "original": self.original[:160],
            "repaired": self.repaired[:160],
            "reason": self.reason,
        }


def repair_dropcap_html(html: str) -> Tuple[str, List[DropcapRepair]]:
    """Repair unambiguous dropcap corruptions in one XHTML document."""
    changes: List[DropcapRepair] = []

    def replace(match: re.Match) -> str:
        opening, inner, closing, tail = match.groups()
        content = _TAG_RE.sub("", inner).strip()
        if not content or "[" in content or "]" in content or "<" in content:
            return match.group(0)

        new_content = ""
        new_tail = tail
        reason = ""
        if len(content) == 1 and tail and tail[0].isupper():
            # The source letter was kept in front of a translated word:
            # "A" + "Uma" -> wrap the U and leave "ma".
            new_content = tail[0]
            new_tail = tail[1:]
            reason = "moved the first letter of the following word into the dropcap"
        elif len(content) > 1 and content.isalpha() and tail and not tail.startswith("<"):
            # The whole word landed inside the span: "estudos" + " servem"
            # -> wrap "e" and leave "studos servem".
            new_content = content[0]
            new_tail = content[1:] + tail
            reason = "moved the rest of the over-long dropcap back into the text"

        if not new_content:
            return match.group(0)
        repaired = f"{opening}{new_content}{closing}{new_tail}"
        changes.append(
            DropcapRepair(
                original=match.group(0),
                repaired=repaired,
                reason=reason,
            )
        )
        return repaired

    return _DROPCAP_RE.sub(replace, html or ""), changes


def repair_dropcaps_in_epub(source_path: str, output_path: str) -> Dict[str, object]:
    """Copy an EPUB, repairing dropcap spans in XHTML documents."""
    changed_files: List[Dict[str, object]] = []
    total = 0
    with zipfile.ZipFile(source_path, "r") as source, zipfile.ZipFile(
        output_path, "w", zipfile.ZIP_DEFLATED
    ) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.lower().endswith((".xhtml", ".html", ".htm")):
                text = data.decode("utf-8", "replace")
                repaired, changes = repair_dropcap_html(text)
                if changes:
                    data = repaired.encode("utf-8")
                    total += len(changes)
                    changed_files.append(
                        {
                            "file": item.filename,
                            "changes": [change.to_dict() for change in changes],
                        }
                    )
            target.writestr(item, data)
    return {
        "source": source_path,
        "out": output_path,
        "changed_files": changed_files,
        "total_changes": total,
    }


def repair_invalid_doc_roles_html(html: str) -> Tuple[str, List[Dict[str, str]]]:
    """Remove DPUB-ARIA ``role="doc-*"`` from ``<body>``.

    EPUBCheck 5.4.0 rejects those roles on the XHTML body element even though
    the same documents carry the semantic in ``epub:type``. Removing the
    redundant role is non-destructive and keeps the EPUB 3 type.
    """
    changes: List[Dict[str, str]] = []

    def replace(match: re.Match) -> str:
        changes.append({"removed": match.group(0)[len(match.group(1)) :].strip()})
        return match.group(1)

    return _BODY_DOC_ROLE_RE.sub(replace, html or ""), changes


def repair_doc_roles_in_epub(source_path: str, output_path: str) -> Dict[str, object]:
    """Copy an EPUB, removing invalid DPUB-ARIA roles from body elements."""
    changed_files: List[Dict[str, object]] = []
    total = 0
    with zipfile.ZipFile(source_path, "r") as source, zipfile.ZipFile(
        output_path, "w", zipfile.ZIP_DEFLATED
    ) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.lower().endswith((".xhtml", ".html", ".htm")):
                text = data.decode("utf-8", "replace")
                repaired, changes = repair_invalid_doc_roles_html(text)
                if changes:
                    data = repaired.encode("utf-8")
                    total += len(changes)
                    changed_files.append({"file": item.filename, "changes": changes})
            target.writestr(item, data)
    return {
        "source": source_path,
        "out": output_path,
        "changed_files": changed_files,
        "total_changes": total,
    }


TEXT_ENTRY_SUFFIXES = (".xhtml", ".html", ".htm", ".opf", ".ncx")
_ID_ATTR_RE = re.compile(r"""(\sid\s*=\s*["'])([^"']*)""")


def _invalid_xml_id(value: str) -> bool:
    """An XML name starts with a letter or an underscore; a digit does not."""
    return bool(value) and not (value[0].isalpha() or value[0] == "_")


def repair_invalid_ids_in_epub(source_path: str, output_path: str) -> Dict[str, object]:
    """Copy an EPUB, renaming ``id`` values that are not valid XML names.

    An id that starts with a digit is an EPUBCheck error (RSC-005 in the XHTML, RSC-012 for
    the fragment that points at it). The id gets a leading underscore, and every ``#id``
    fragment reference in the XHTML, OPF and NCX is renamed with it. Nothing else changes.
    """
    with zipfile.ZipFile(source_path, "r") as source:
        items = source.infolist()
        contents = {item.filename: source.read(item.filename) for item in items}

    texts = {
        name: contents[name].decode("utf-8", "replace")
        for name in contents
        if name.lower().endswith(TEXT_ENTRY_SUFFIXES)
    }
    existing: set = set()
    invalid: set = set()
    for text in texts.values():
        for match in _ID_ATTR_RE.finditer(text):
            value = match.group(2)
            existing.add(value)
            if _invalid_xml_id(value):
                invalid.add(value)

    rename: Dict[str, str] = {}
    for value in sorted(invalid):
        new = "_" + value
        while new in existing:
            new = "_" + new
        existing.add(new)
        rename[value] = new

    changes: Dict[str, int] = {}
    if rename:
        alternation = "|".join(re.escape(value) for value in sorted(rename, key=len, reverse=True))
        pattern = re.compile(r"""(\sid\s*=\s*["']|#)(""" + alternation + r""")(?=["'])""")

        def swap(match: re.Match) -> str:
            return match.group(1) + rename[match.group(2)]

        for name, text in texts.items():
            new_text, count = pattern.subn(swap, text)
            if count:
                texts[name] = new_text
                changes[name] = count

    changed_files: List[Dict[str, object]] = []
    total = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as target:
        for item in items:
            data = contents[item.filename]
            if item.filename in changes:
                data = texts[item.filename].encode("utf-8")
                total += changes[item.filename]
                changed_files.append({"file": item.filename, "changes": changes[item.filename]})
            target.writestr(item, data)
    return {
        "source": source_path,
        "out": output_path,
        "renamed_ids": rename,
        "changed_files": changed_files,
        "total_changes": total,
    }


_IMG_NO_ALT_RE = re.compile(r"<img(?![^>]*\balt\s*=)([^>]*?)(/?)>", re.IGNORECASE)
_P_BLOCK_WRAP_RE = re.compile(
    r"<p\b[^>]*>\s*(<h[1-6]\b[^>]*>.*?</h[1-6]>\s*<ul\b[^>]*>.*?</ul>)\s*</p>",
    re.IGNORECASE | re.DOTALL,
)
_A_NAME_NO_ID_RE = re.compile(
    r'(<a\b(?![^>]*\bid\s*=)[^>]*?)\s*\bname\s*=\s*(["\'])([^"\']+)\2([^>]*>)',
    re.IGNORECASE,
)
_NESTED_CEPS_P_RE = re.compile(
    r'(<p\b[^>]*\bclass="ceps"[^>]*>(?:(?!</p>).)*?)\s*<p\b([^>]*)>\s*([^<]*?)\s*</p>\s*[\'’]?\s*(?:<small\b[^>]*/>\s*)*',
    re.IGNORECASE | re.DOTALL,
)
_XML_NCNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")


def _hygiene_fix_opf(opf_text: str) -> tuple[str, int, str]:
    import html
    import uuid

    changes = 0
    updated = opf_text

    if re.search(r'\bversion\s*=\s*(["\'])2\.', updated):
        updated, c1 = re.subn(
            r'\s*<(?:[a-zA-Z0-9]+:)?meta\b[^>]*\b(?:property|refines)\s*=[^>]*>.*?</(?:[a-zA-Z0-9]+:)?meta>',
            "",
            updated,
            flags=re.DOTALL,
        )
        updated, c2 = re.subn(
            r'\s*<(?:[a-zA-Z0-9]+:)?meta\b[^>]*\b(?:property|refines)\s*=[^>]*/?>',
            "",
            updated,
        )
        changes += c1 + c2

    updated, c_guide = re.subn(
        r'\s*<(?:[a-zA-Z0-9]+:)?guide\s*(?:/>|>\s*</(?:[a-zA-Z0-9]+:)?guide>)',
        "",
        updated,
    )
    changes += c_guide

    uid_match = re.search(r'unique-identifier\s*=\s*(["\'])([^"\']+)\1', updated)
    if uid_match:
        target_uid = uid_match.group(2)
        if not re.search(rf'\bid\s*=\s*(["\']){re.escape(target_uid)}\1', updated):
            id_candidates: List[str] = []
            unid_matches = []
            for match in re.finditer(
                r"<dc:identifier\b([^>]*)>(.*?)</dc:identifier>", updated, re.DOTALL
            ):
                attrs = match.group(1)
                id_m = re.search(r'\bid\s*=\s*(["\'])([^"\']+)\1', attrs)
                is_isbn = "isbn" in attrs.lower() or (id_m and "isbn" in id_m.group(2).lower())
                if id_m and not is_isbn:
                    id_candidates.append(id_m.group(2))
                elif not id_m and not is_isbn:
                    unid_matches.append(match)

            if id_candidates:
                chosen = id_candidates[0]
                updated = re.sub(
                    r'unique-identifier\s*=\s*(["\'])([^"\']+)\1',
                    f'unique-identifier="{chosen}"',
                    updated,
                    count=1,
                )
                changes += 1
            elif unid_matches:
                match = unid_matches[0]
                replacement = (
                    f'<dc:identifier id="{html.escape(target_uid)}"{match.group(1)}>'
                    f"{match.group(2)}</dc:identifier>"
                )
                updated = updated[: match.start()] + replacement + updated[match.end() :]
                changes += 1
            else:
                first_dc = re.search(r"<dc:identifier\b([^>]*)>", updated)
                if first_dc and not re.search(r"\bid\s*=", first_dc.group(1)):
                    replacement = f'<dc:identifier id="{html.escape(target_uid)}"{first_dc.group(1)}>'
                    updated = updated[: first_dc.start()] + replacement + updated[first_dc.end() :]
                    changes += 1
                else:
                    meta_close = re.search(r"</(?:[a-zA-Z0-9]+:)?metadata>", updated)
                    if meta_close:
                        inject = (
                            f'  <dc:identifier id="{html.escape(target_uid)}">'
                            f"urn:uuid:{uuid.uuid4()}</dc:identifier>\n  "
                        )
                        updated = updated[: meta_close.start()] + inject + updated[meta_close.start() :]
                        changes += 1

    final_uid_m = re.search(r'unique-identifier\s*=\s*(["\'])([^"\']+)\1', updated)
    uid_value = ""
    if final_uid_m:
        esc_uid = re.escape(final_uid_m.group(2))
        dc_val_m = re.search(
            rf"<dc:identifier\b[^>]*\bid\s*=\s*([\"']){esc_uid}\1[^>]*>(.*?)</dc:identifier>",
            updated,
            re.DOTALL,
        )
        if dc_val_m:
            uid_value = re.sub(r"<[^>]+>", "", dc_val_m.group(2)).strip()

    return updated, changes, uid_value


def _hygiene_fix_html_structure(text: str, *, default_lang: str = "pt-BR") -> tuple[str, int]:
    changes = 0
    text, lang_count = re.subn(
        r'\b((?:xml:)?lang\s*=\s*)(["\'])\s*\2',
        rf"\1\g<2>{default_lang}\g<2>",
        text,
        flags=re.IGNORECASE,
    )
    changes += lang_count
    text, img_count = _IMG_NO_ALT_RE.subn(r'<img\1 alt=""\2>', text)
    changes += img_count
    text, unwrap_count = _P_BLOCK_WRAP_RE.subn(r"\1", text)
    changes += unwrap_count
    text, ceps_unwrap_count = _NESTED_CEPS_P_RE.subn(
        r'\1 <small class="calibre5">\3</small></p>\n\n<p\2>',
        text,
    )
    changes += ceps_unwrap_count

    def _replace_name(match: re.Match[str]) -> str:
        nonlocal changes
        prefix, quote, val, suffix = match.groups()
        changes += 1
        if _XML_NCNAME_RE.match(val):
            return f"{prefix} id={quote}{val}{quote}{suffix}"
        return f"{prefix}{suffix}"

    text = _A_NAME_NO_ID_RE.sub(_replace_name, text)
    return text, changes


_NCX_MINOR_PT_WORDS = {
    "a", "as", "à", "às", "ao", "aos", "com", "da", "das", "de", "do", "dos",
    "e", "em", "na", "nas", "no", "nos", "o", "os", "ou", "para", "pela",
    "pelas", "pelo", "pelos", "por", "sem", "sob", "sobre", "um", "uma",
}


def _format_pt_toc_part(part: str) -> str:
    cleaned = re.sub(r"\s+", " ", part).strip()
    if not cleaned:
        return ""
    if cleaned.isupper() or cleaned.islower():
        words = cleaned.split(" ")
        formatted = []
        for idx, word in enumerate(words):
            low = word.casefold()
            if idx > 0 and low in _NCX_MINOR_PT_WORDS:
                formatted.append(low)
            elif "-" in low:
                formatted.append(
                    "-".join(
                        seg
                        if (idx > 0 and i > 0 and seg in _NCX_MINOR_PT_WORDS)
                        else seg[:1].upper() + seg[1:]
                        for i, seg in enumerate(low.split("-"))
                    )
                )
            else:
                formatted.append(low[:1].upper() + low[1:])
        return " ".join(formatted)
    return cleaned


def _hygiene_fix_bloated_ncx_labels(
    ncx_text: str, ncx_name: str, texts: Dict[str, str]
) -> tuple[str, int]:
    """Replace prose-bloated NCX labels (>120 chars) with short headings from the target file."""
    import html
    import posixpath

    ncx_dir = posixpath.dirname(ncx_name)
    changes = 0
    heading_re = re.compile(
        r"<h[1-4]\b[^>]*>(.*?)</h[1-4]>|"
        r'<p\b[^>]*\bclass="[^"]*\b(?:cn|ccn|fmh|cfmh|ct|acmh)\b[^"]*"[^>]*>(.*?)</p>',
        re.IGNORECASE | re.DOTALL,
    )
    point_re = re.compile(
        r'(<navLabel>\s*<text>)(.*?)(</text>\s*</navLabel>\s*<content\b[^>]*\bsrc\s*=\s*(["\'])([^"\']+)\4)',
        re.IGNORECASE | re.DOTALL,
    )

    def _repl(match: re.Match[str]) -> str:
        nonlocal changes
        prefix, raw_label, suffix, _quote, src = match.groups()
        plain = re.sub(r"\s+", " ", html.unescape(raw_label)).strip()
        if len(plain) <= 120:
            return match.group(0)

        rel_href = src.split("#", 1)[0]
        href_file = posixpath.normpath(
            posixpath.join(ncx_dir, rel_href) if ncx_dir else rel_href
        )
        low_href = href_file.lower()
        clean_label = ""
        if low_href.endswith(("_adc_r1.htm", "_adc_r1.html", "adc.xhtml", "adc.htm")):
            clean_label = "Obras do Autor"
        elif low_href.endswith(("_cop_r1.htm", "_cop_r1.html", "cop.xhtml", "cop.htm")):
            clean_label = "Créditos"
        else:
            doc_html = texts.get(href_file) or texts.get(rel_href) or ""
            parts: List[str] = []
            for h_m in heading_re.finditer(doc_html):
                raw_h = h_m.group(1) if h_m.group(1) is not None else h_m.group(2)
                text_h = re.sub(
                    r"\s+", " ", html.unescape(_TAG_RE.sub("", raw_h or ""))
                ).strip()
                if text_h and len(text_h) <= 90:
                    parts.append(_format_pt_toc_part(text_h))
                    if len(parts) >= 2:
                        break
            if parts:
                clean_label = " — ".join(parts)

        if not clean_label:
            clean_label = (plain[:77].rstrip() + "...") if len(plain) > 80 else plain

        changes += 1
        return f"{prefix}{html.escape(clean_label, quote=False)}{suffix}"

    updated = point_re.sub(_repl, ncx_text)
    return updated, changes


def repair_epubcheck_hygiene_in_epub(source_path: str, output_path: str) -> Dict[str, object]:
    """Fix common structural EPUBCheck hygiene errors in ``source_path``."""
    import posixpath

    html_suffixes = (".xhtml", ".html", ".htm")
    with zipfile.ZipFile(source_path, "r") as source:
        items = source.infolist()
        contents = {item.filename: source.read(item.filename) for item in items}

    texts: Dict[str, str] = {
        name: contents[name].decode("utf-8", "replace")
        for name in contents
        if name.lower().endswith(TEXT_ENTRY_SUFFIXES + (".css",))
    }
    changes: Dict[str, int] = {}

    opf_uid_value = ""
    default_lang = "pt-BR"
    for name in list(texts):
        if name.lower().endswith(".opf"):
            lang_m = re.search(r"<dc:language\b[^>]*>(.*?)</dc:language>", texts[name], re.DOTALL)
            if lang_m:
                cand_lang = re.sub(r"<[^>]+>", "", lang_m.group(1)).strip()
                if cand_lang:
                    default_lang = cand_lang
            updated, count, opf_uid_value = _hygiene_fix_opf(texts[name])
            if count:
                texts[name] = updated
                changes[name] = changes.get(name, 0) + count

    for name in list(texts):
        if name.lower().endswith(html_suffixes):
            updated, count = _hygiene_fix_html_structure(texts[name], default_lang=default_lang)
            if count:
                texts[name] = updated
                changes[name] = changes.get(name, 0) + count

    # Collect valid ids across all HTML documents after name/id upgrades.
    html_ids: Dict[str, set] = {}
    for name, text in texts.items():
        if name.lower().endswith(html_suffixes):
            html_ids[name] = {
                m.group(2)
                for m in re.finditer(r"""\b(?:id|name)\s*=\s*(["'])([^"']+)\1""", text)
            }

    def _strip_dangling_hrefs(
        doc_name: str, text: str, attr_pattern: str
    ) -> tuple[str, int]:
        doc_dir = posixpath.dirname(doc_name)
        base_name = posixpath.basename(doc_name)
        count = 0

        def _repl(match: re.Match[str]) -> str:
            nonlocal count
            prefix, quote, raw_ref, suffix = match.groups()
            if raw_ref.startswith(("http://", "https://", "mailto:", "data:", "javascript:")):
                return match.group(0)
            doc_part, sep, frag = raw_ref.partition("#")
            if not sep or not frag:
                return match.group(0)
            target = (
                doc_name
                if not doc_part
                else posixpath.normpath(posixpath.join(doc_dir, doc_part) if doc_dir else doc_part)
            )
            if target not in html_ids or frag in html_ids[target]:
                return match.group(0)
            count += 1
            clean_ref = doc_part if doc_part else base_name
            return f"{prefix}{quote}{clean_ref}{quote}{suffix}"

        return re.sub(attr_pattern, _repl, text, flags=re.IGNORECASE), count

    def _fix_html_href_extensions(doc_name: str, text: str) -> tuple[str, int]:
        doc_dir = posixpath.dirname(doc_name)
        count = 0

        def _repl(match: re.Match[str]) -> str:
            nonlocal count
            prefix, quote, raw_ref, suffix = match.groups()
            if raw_ref.startswith(("http://", "https://", "mailto:", "data:", "javascript:", "#")):
                return match.group(0)
            doc_part, sep, frag = raw_ref.partition("#")
            if not doc_part or not doc_part.lower().endswith(html_suffixes):
                return match.group(0)
            target = posixpath.normpath(posixpath.join(doc_dir, doc_part) if doc_dir else doc_part)
            if target in contents:
                return match.group(0)
            stem, _ext = posixpath.splitext(target)
            part_stem, _part_ext = posixpath.splitext(doc_part)
            for alt_ext in html_suffixes:
                if f"{stem}{alt_ext}" in contents:
                    count += 1
                    new_ref = f"{part_stem}{alt_ext}{sep}{frag}"
                    return f"{prefix}{quote}{new_ref}{quote}{suffix}"
            return match.group(0)

        return (
            re.sub(
                r'(<a\b[^>]*\bhref\s*=\s*)(["\'])([^"\']+)\2([^>]*>)',
                _repl,
                text,
                flags=re.IGNORECASE,
            ),
            count,
        )

    def _hygiene_drop_missing_font_faces(css_name: str, css_text: str) -> tuple[str, int]:
        css_dir = posixpath.dirname(css_name)
        count = 0

        def _repl(match: re.Match[str]) -> str:
            nonlocal count
            block = match.group(0)
            urls = re.findall(r'url\(\s*["\']?([^"\')\s]+)["\']?\s*\)', block, flags=re.IGNORECASE)
            if not urls:
                return block
            for raw_url in urls:
                if raw_url.startswith(("http://", "https://", "data:")):
                    continue
                target = posixpath.normpath(posixpath.join(css_dir, raw_url) if css_dir else raw_url)
                if target in contents:
                    return block
            count += 1
            return ""

        updated = re.sub(r"@font-face\s*\{[^}]*\}", _repl, css_text, flags=re.IGNORECASE | re.DOTALL)
        return updated, count

    for name in list(texts):
        low = name.lower()
        if low.endswith(html_suffixes):
            updated, ext_count = _fix_html_href_extensions(name, texts[name])
            if ext_count:
                texts[name] = updated
                changes[name] = changes.get(name, 0) + ext_count
            updated, count = _strip_dangling_hrefs(
                name, texts[name], r'(<a\b[^>]*\bhref\s*=\s*)(["\'])([^"\']+)\2([^>]*>)'
            )
            if count:
                texts[name] = updated
                changes[name] = changes.get(name, 0) + count
        elif low.endswith(".css"):
            updated, css_count = _hygiene_drop_missing_font_faces(name, texts[name])
            if css_count:
                texts[name] = updated
                changes[name] = changes.get(name, 0) + css_count
        elif low.endswith(".ncx"):
            ncx_text = texts[name]
            ncx_changes = 0
            if opf_uid_value:
                dtb_m = re.search(
                    r'<meta\b[^>]*\bname\s*=\s*(["\'])dtb:uid\1[^>]*/?>',
                    ncx_text,
                    re.IGNORECASE,
                )
                if dtb_m:
                    cur_m = re.search(r'\bcontent\s*=\s*(["\'])([^"\']*)\1', dtb_m.group(0))
                    if cur_m and cur_m.group(2).strip() != opf_uid_value:
                        import html as _html

                        new_meta = re.sub(
                            r'\bcontent\s*=\s*(["\'])[^"\']*\1',
                            f'content="{_html.escape(opf_uid_value)}"',
                            dtb_m.group(0),
                            count=1,
                        )
                        ncx_text = (
                            ncx_text[: dtb_m.start()] + new_meta + ncx_text[dtb_m.end() :]
                        )
                        ncx_changes += 1
            if re.search(r'playOrder\s*=\s*(["\'])0\1', ncx_text):
                order = [0]

                def _renumber(_match: re.Match[str]) -> str:
                    order[0] += 1
                    return f'playOrder="{order[0]}"'

                ncx_text, p_count = re.subn(
                    r'playOrder\s*=\s*(["\'])\d+\1', _renumber, ncx_text
                )
                ncx_changes += p_count
            ncx_text, href_count = _strip_dangling_hrefs(
                name, ncx_text, r'(<content\b[^>]*\bsrc\s*=\s*)(["\'])([^"\']+)\2([^>]*/?>)'
            )
            ncx_changes += href_count
            ncx_text, label_count = _hygiene_fix_bloated_ncx_labels(
                ncx_text, name, texts
            )
            ncx_changes += label_count
            if ncx_changes:
                texts[name] = ncx_text
                changes[name] = changes.get(name, 0) + ncx_changes

    changed_files: List[Dict[str, object]] = []
    total = 0
    with zipfile.ZipFile(output_path, "w") as target:
        if "mimetype" in contents:
            zinfo = zipfile.ZipInfo("mimetype")
            target.writestr(zinfo, contents["mimetype"], compress_type=zipfile.ZIP_STORED)
        for item in items:
            if item.filename == "mimetype":
                continue
            data = contents[item.filename]
            if item.filename in changes:
                data = texts[item.filename].encode("utf-8")
                total += changes[item.filename]
                changed_files.append({"file": item.filename, "changes": changes[item.filename]})
            item.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(item, data)

    return {
        "source": source_path,
        "out": output_path,
        "changed_files": changed_files,
        "total_changes": total,
    }
