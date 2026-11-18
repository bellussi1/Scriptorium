"""Read-only source EPUB inspection and non-destructive preparation helpers."""

from __future__ import annotations

import html
import os
import posixpath
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREPARED_DIR = ROOT / "data" / "calibre" / "prepared"

HTML_EXTENSIONS = (".xhtml", ".html", ".htm")

FILE_URI_RE = re.compile(r"\s*file:///[^\n<]+", re.IGNORECASE)
PAGE_COUNT_RE = re.compile(r"\(\s*\d+\s+of\s+\d+\s*\)", re.IGNORECASE)
IMG_MISSING_ALT_RE = re.compile(r"<img(?![^>]*\balt\s*=)([^>]*?)(/?)>", re.IGNORECASE)
LEGACY_NAME_ATTR_RE = re.compile(
    r'(<a\b(?![^>]*\bid\s*=)[^>]*?)\s*\bname\s*=\s*(["\'])([^"\']+)\2([^>]*>)',
    re.IGNORECASE,
)
TITLE_FILE_URI_RE = re.compile(r"(<title[^>]*>)\s*file:///[^<]+(</title>)", re.IGNORECASE)
P_BLOCK_RE = re.compile(r"(<p\b[^>]*>)(.*?)(</p>)", re.IGNORECASE | re.DOTALL)
TAG_STRIP_RE = re.compile(r"<[^>]+>")
CHAPTER_HEADING_RE = re.compile(
    r"^(?:PROLOGUE(?:\s*[-—:]\s*.*)?|EPILOGUE(?:\s*[-—:]\s*.*)?|"
    r"CHAPTER\s+(?:[A-Z]+(?:-[A-Z]+)*|\d+)(?:\s*[-—:]\s*.*)?)$"
)
BOLD_ONLY_RE = re.compile(r"^\s*<b(\b[^>]*)>(.*?)</b>\s*$", re.IGNORECASE | re.DOTALL)
SENTENCE_END_CHARS = (".", "!", "?", "…", '"', "'", "”", "’", ")", "—", ":")


def slugify_title(title: str) -> str:
    """Return a filesystem-safe lowercase hyphenated slug for a book title."""
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-") or "book"


def _extract_title(book_or_title: Any) -> str:
    if isinstance(book_or_title, str):
        return book_or_title
    return str(getattr(book_or_title, "title", "") or "")


def prepared_source_path(
    book_or_title: Any,
    prepared_dir: Optional[Path | str] = None,
) -> Path:
    """Return the prepared EPUB path for a book under ``data/calibre/prepared``."""
    base = Path(prepared_dir) if prepared_dir is not None else DEFAULT_PREPARED_DIR
    return base / f"{slugify_title(_extract_title(book_or_title))}.epub"


def _strip_tags(fragment: str) -> str:
    text = TAG_STRIP_RE.sub("", fragment or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _opf_has_valid_unique_identifier(opf_text: str) -> bool:
    match = re.search(r'unique-identifier\s*=\s*(["\'])([^"\']+)\1', opf_text)
    if not match:
        return True
    uid = match.group(2)
    return bool(re.search(rf'\bid\s*=\s*(["\']){re.escape(uid)}\1', opf_text))


def _extract_opf_uid_value(opf_text: str) -> str:
    match = re.search(r'unique-identifier\s*=\s*(["\'])([^"\']+)\1', opf_text)
    if not match:
        return ""
    uid = re.escape(match.group(2))
    dc_match = re.search(
        rf"<dc:identifier\b[^>]*\bid\s*=\s*([\"']){uid}\1[^>]*>(.*?)</dc:identifier>",
        opf_text,
        re.DOTALL,
    )
    return _strip_tags(dc_match.group(2)) if dc_match else ""


def _extract_ncx_dtb_uid(ncx_text: str) -> str:
    meta_match = re.search(
        r'<meta\b[^>]*\bname\s*=\s*(["\'])dtb:uid\1[^>]*/?>',
        ncx_text,
        re.IGNORECASE,
    )
    if not meta_match:
        return ""
    content_match = re.search(r'\bcontent\s*=\s*(["\'])([^"\']*)\1', meta_match.group(0))
    return content_match.group(2).strip() if content_match else ""


def _set_ncx_dtb_uid(ncx_text: str, uid_value: str) -> str:
    if not uid_value:
        return ncx_text
    escaped = html.escape(uid_value)

    def _update_meta(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r'\bcontent\s*=', tag):
            return re.sub(
                r'\bcontent\s*=\s*(["\'])[^"\']*\1',
                f'content="{escaped}"',
                tag,
                count=1,
            )
        return tag[:-2] + f' content="{escaped}"/>' if tag.endswith("/>") else tag[:-1] + f' content="{escaped}">'

    return re.sub(
        r'<meta\b[^>]*\bname\s*=\s*(["\'])dtb:uid\1[^>]*/?>',
        _update_meta,
        ncx_text,
        count=1,
        flags=re.IGNORECASE,
    )


def _clean_opf_epub2_hygiene(opf_text: str) -> str:
    updated = opf_text
    if re.search(r'\bversion\s*=\s*(["\'])2\.', updated):
        updated = re.sub(
            r'\s*<(?:[a-zA-Z0-9]+:)?meta\b[^>]*\b(?:property|refines)\s*=[^>]*>.*?</(?:[a-zA-Z0-9]+:)?meta>',
            "",
            updated,
            flags=re.DOTALL,
        )
        updated = re.sub(
            r'\s*<(?:[a-zA-Z0-9]+:)?meta\b[^>]*\b(?:property|refines)\s*=[^>]*/?>',
            "",
            updated,
        )
    updated = re.sub(
        r'\s*<(?:[a-zA-Z0-9]+:)?guide\s*(?:/>|>\s*</(?:[a-zA-Z0-9]+:)?guide>)',
        "",
        updated,
    )
    return updated


def _is_doc_outline_html(text: str) -> bool:
    return "Document Outline" in text and ("<ul" in text or "Local Disk" in text)


def _html_entries_in_reading_order(
    namelist: List[str], opf_path: Optional[str], opf_text: str
) -> List[str]:
    html_set = {n for n in namelist if n.lower().endswith(HTML_EXTENSIONS)}
    if not opf_path or not opf_text:
        return sorted(html_set)

    opf_dir = posixpath.dirname(opf_path)
    items: Dict[str, str] = {}
    for m in re.finditer(r"<(?:[a-zA-Z0-9]+:)?item\b([^>]+)/?>", opf_text):
        attrs = m.group(1)
        id_m = re.search(r'\bid\s*=\s*(["\'])([^"\']+)\1', attrs)
        href_m = re.search(r'\bhref\s*=\s*(["\'])([^"\']+)\1', attrs)
        if id_m and href_m:
            joined = posixpath.normpath(
                posixpath.join(opf_dir, href_m.group(2)) if opf_dir else href_m.group(2)
            )
            items[id_m.group(2)] = joined

    ordered: List[str] = []
    seen = set()
    for m in re.finditer(r"<(?:[a-zA-Z0-9]+:)?itemref\b([^>]+)/?>", opf_text):
        idref_m = re.search(r'\bidref\s*=\s*(["\'])([^"\']+)\1', m.group(1))
        if idref_m:
            target = items.get(idref_m.group(2))
            if target and target in html_set and target not in seen:
                seen.add(target)
                ordered.append(target)

    for extra in sorted(html_set):
        if extra not in seen:
            ordered.append(extra)
    return ordered


def _find_toc_r1_entry(html_files: List[str]) -> Optional[str]:
    for name in html_files:
        low = name.lower()
        if "_toc_r1." in low or low.endswith("_toc.htm") or low.endswith("_toc.xhtml"):
            return name
    return None


def _count_extracted_headings(contents: Dict[str, str], html_files: List[str]) -> int:
    count = 0
    for name in html_files:
        text = contents[name]
        if _is_doc_outline_html(text):
            continue
        for m in P_BLOCK_RE.finditer(text):
            plain = _strip_tags(m.group(2))
            if plain and len(plain) <= 120 and CHAPTER_HEADING_RE.match(plain):
                count += 1
    return count


def inspect_source_epub(source_path: Path | str) -> Dict[str, Any]:
    """Inspect an EPUB archive read-only and report structural preparation needs."""
    src = Path(source_path)
    with zipfile.ZipFile(src, "r") as zf:
        names = zf.namelist()
        opf_path = next((n for n in names if n.lower().endswith(".opf")), None)
        ncx_path = next((n for n in names if n.lower().endswith(".ncx")), None)
        opf_text = zf.read(opf_path).decode("utf-8", "ignore") if opf_path else ""
        ncx_text = zf.read(ncx_path).decode("utf-8", "ignore") if ncx_path else ""

        html_files = _html_entries_in_reading_order(names, opf_path, opf_text)
        html_contents = {name: zf.read(name).decode("utf-8", "ignore") for name in html_files}

    uid_ok = _opf_has_valid_unique_identifier(opf_text) if opf_text else True
    is_epub2 = bool(re.search(r'\bversion\s*=\s*(["\'])2\.', opf_text))
    epub3_meta_in_epub2 = bool(
        is_epub2
        and re.search(
            r"<(?:[a-zA-Z0-9]+:)?meta\b[^>]*\b(?:property|refines)\s*=",
            opf_text,
        )
    )
    empty_guide = bool(
        re.search(
            r"<(?:[a-zA-Z0-9]+:)?guide\s*(?:/>|>\s*</(?:[a-zA-Z0-9]+:)?guide>)",
            opf_text,
        )
    )
    empty_html_lang = any(
        re.search(r'\b(?:xml:)?lang\s*=\s*(["\'])\s*\1', body, re.IGNORECASE)
        for body in html_contents.values()
    )
    opf_uid_val = _extract_opf_uid_value(opf_text)
    ncx_uid_val = _extract_ncx_dtb_uid(ncx_text)
    ncx_uid_mismatch = bool(
        ncx_path
        and (not uid_ok or (opf_uid_val and ncx_uid_val and opf_uid_val != ncx_uid_val))
    )

    nav_points = len(re.findall(r"<navPoint\b", ncx_text))
    play_order_zero = bool(re.search(r'playOrder\s*=\s*(["\'])0\1', ncx_text))
    ncx_file_title = "file:///" in ncx_text.lower()

    doc_outline_files = [name for name, body in html_contents.items() if _is_doc_outline_html(body)]
    pdftohtml = any("pdftohtml" in body.lower() for body in html_contents.values())
    has_file_uri = any(FILE_URI_RE.search(body) for body in html_contents.values())
    has_page_footer = any(PAGE_COUNT_RE.search(body) for body in html_contents.values())
    bad_html_titles = any(TITLE_FILE_URI_RE.search(body) for body in html_contents.values())
    missing_alt_count = sum(
        len(IMG_MISSING_ALT_RE.findall(body)) for body in html_contents.values()
    )
    legacy_name_count = sum(
        len(LEGACY_NAME_ATTR_RE.findall(body)) for body in html_contents.values()
    )

    toc_r1_path = _find_toc_r1_entry(html_files)
    extracted_headings = 0
    if nav_points <= 2 and toc_r1_path is None:
        extracted_headings = _count_extracted_headings(html_contents, html_files)

    needs_ncx_rebuild = bool(
        ncx_path
        and nav_points <= 2
        and (
            (toc_r1_path is not None and nav_points <= 1)
            or (extracted_headings >= 2 and extracted_headings > nav_points)
        )
    )

    needs_prep = any(
        [
            not uid_ok,
            epub3_meta_in_epub2,
            empty_guide,
            empty_html_lang,
            ncx_uid_mismatch,
            play_order_zero,
            ncx_file_title,
            bool(doc_outline_files),
            pdftohtml,
            has_file_uri,
            has_page_footer,
            bad_html_titles,
            missing_alt_count > 0,
            legacy_name_count > 0,
            needs_ncx_rebuild,
        ]
    )

    return {
        "needs_prep": needs_prep,
        "opf_path": opf_path,
        "ncx_path": ncx_path,
        "uid_ok": uid_ok,
        "epub3_meta_in_epub2": epub3_meta_in_epub2,
        "empty_guide": empty_guide,
        "empty_html_lang": empty_html_lang,
        "ncx_uid_mismatch": ncx_uid_mismatch,
        "nav_points": nav_points,
        "play_order_zero": play_order_zero,
        "doc_outline_files": doc_outline_files,
        "pdftohtml": pdftohtml,
        "has_file_uri": has_file_uri,
        "has_page_footer": has_page_footer,
        "bad_html_titles": bad_html_titles,
        "missing_alt_count": missing_alt_count,
        "legacy_name_count": legacy_name_count,
        "toc_r1_path": toc_r1_path,
        "extracted_headings": extracted_headings,
        "needs_ncx_rebuild": needs_ncx_rebuild,
    }


def _fix_opf_unique_identifier(opf_text: str) -> str:
    if _opf_has_valid_unique_identifier(opf_text):
        return opf_text

    uid_match = re.search(r'unique-identifier\s*=\s*(["\'])([^"\']+)\1', opf_text)
    target_uid = uid_match.group(2) if uid_match else "uuid_id"

    # Prefer reusing an existing non-ISBN dc:identifier's id (e.g. kre-calibre-uuid / BookId).
    id_candidates = []
    unid_candidates = []
    for m in re.finditer(r"<dc:identifier\b([^>]*)>(.*?)</dc:identifier>", opf_text, re.DOTALL):
        attrs = m.group(1)
        id_m = re.search(r'\bid\s*=\s*(["\'])([^"\']+)\1', attrs)
        is_isbn = "isbn" in attrs.lower() or (id_m and "isbn" in id_m.group(2).lower())
        if id_m and not is_isbn:
            id_candidates.append(id_m.group(2))
        elif not id_m and not is_isbn:
            unid_candidates.append(m)

    if id_candidates and uid_match:
        chosen = id_candidates[0]
        return re.sub(
            r'unique-identifier\s*=\s*(["\'])([^"\']+)\1',
            f'unique-identifier="{chosen}"',
            opf_text,
            count=1,
        )

    if unid_candidates:
        m = unid_candidates[0]
        updated_tag = f"<dc:identifier id=\"{html.escape(target_uid)}\"{m.group(1)}>{m.group(2)}</dc:identifier>"
        return opf_text[: m.start()] + updated_tag + opf_text[m.end() :]

    # Fallback: add id to the first dc:identifier or synthesize one inside metadata.
    first_dc = re.search(r"<dc:identifier\b([^>]*)>", opf_text)
    if first_dc and not re.search(r'\bid\s*=', first_dc.group(1)):
        replacement = f'<dc:identifier id="{html.escape(target_uid)}"{first_dc.group(1)}>'
        return opf_text[: first_dc.start()] + replacement + opf_text[first_dc.end() :]

    generated = str(uuid.uuid4())
    meta_close = re.search(r"</(?:[a-zA-Z0-9]+:)?metadata>", opf_text)
    if meta_close:
        inject = f'  <dc:identifier id="{html.escape(target_uid)}" opf:scheme="uuid">{generated}</dc:identifier>\n  '
        return opf_text[: meta_close.start()] + inject + opf_text[meta_close.start() :]
    return opf_text


def _remove_files_from_opf(opf_text: str, opf_path: str, removed_files: List[str]) -> str:
    if not removed_files:
        return opf_text
    opf_dir = posixpath.dirname(opf_path)
    removed_set = set(removed_files)
    removed_ids = set()

    def _filter_item(match: re.Match[str]) -> str:
        attrs = match.group(1)
        href_m = re.search(r'\bhref\s*=\s*(["\'])([^"\']+)\1', attrs)
        id_m = re.search(r'\bid\s*=\s*(["\'])([^"\']+)\1', attrs)
        if href_m:
            joined = posixpath.normpath(
                posixpath.join(opf_dir, href_m.group(2)) if opf_dir else href_m.group(2)
            )
            if joined in removed_set:
                if id_m:
                    removed_ids.add(id_m.group(2))
                return ""
        return match.group(0)

    updated = re.sub(
        r"\s*<(?:[a-zA-Z0-9]+:)?item\b([^>]*)/?>",
        _filter_item,
        opf_text,
    )
    if removed_ids:
        updated = re.sub(
            r"\s*<(?:[a-zA-Z0-9]+:)?itemref\b[^>]*\bidref\s*=\s*([\"'])("
            + "|".join(re.escape(i) for i in removed_ids)
            + r")\1[^>]*/?>",
            "",
            updated,
        )
    # Remove any guide references pointing to removed files.
    for path in removed_set:
        rel = posixpath.relpath(path, opf_dir) if opf_dir else path
        updated = re.sub(
            rf'\s*<(?:[a-zA-Z0-9]+:)?reference\b[^>]*\bhref\s*=\s*(["\']){re.escape(rel)}(?:#[^"\']*)?\1[^>]*/?>',
            "",
            updated,
        )
    return updated


def _collect_running_headers(html_contents: Dict[str, str], title: str) -> set[str]:
    counts: Dict[str, int] = {}
    for body in html_contents.values():
        if _is_doc_outline_html(body):
            continue
        for m in P_BLOCK_RE.finditer(body):
            inner = m.group(2)
            if "<img" in inner.lower() or "file:///" in inner.lower():
                continue
            plain = _strip_tags(inner)
            if not plain or len(plain) > 80:
                continue
            if CHAPTER_HEADING_RE.match(plain):
                continue
            counts[plain] = counts.get(plain, 0) + 1

    title_low = title.lower().strip()
    headers = set()
    for text, count in counts.items():
        if count < 10:
            continue
        low = text.lower()
        if title_low and (title_low in low or low in title_low or " - " in text):
            headers.add(text)
    return headers


def _upgrade_legacy_anchors_and_imgs(body: str) -> str:
    body = IMG_MISSING_ALT_RE.sub(r'<img\1 alt=""\2>', body)

    def _fix_a(match: re.Match[str]) -> str:
        prefix, quote, name_val, suffix = match.groups()
        # Only valid XML NCNames can be used as id attributes.
        if re.match(r"^[A-Za-z_][A-Za-z0-9_.:-]*$", name_val):
            return f'{prefix} id={quote}{name_val}{quote}{suffix}'
        return f"{prefix}{suffix}"

    body = LEGACY_NAME_ATTR_RE.sub(_fix_a, body)
    return body


def _should_merge_continued_paragraph(prev_plain: str, next_plain: str) -> bool:
    if not prev_plain or not next_plain:
        return False
    if CHAPTER_HEADING_RE.match(prev_plain) or CHAPTER_HEADING_RE.match(next_plain):
        return False
    if prev_plain.rstrip().endswith(SENTENCE_END_CHARS):
        return False
    return bool(re.match(r"^[a-z]", next_plain))


def _can_join_bold_heading(first_plain: str, first_inner: str, next_inner: str) -> bool:
    if not (BOLD_ONLY_RE.match(first_inner) and BOLD_ONLY_RE.match(next_inner)):
        return False
    if not CHAPTER_HEADING_RE.match(first_plain):
        return False
    next_plain = _strip_tags(next_inner)
    if not next_plain or len(next_plain) > 70 or CHAPTER_HEADING_RE.match(next_plain):
        return False
    # Second line of an uppercase heading in pdftohtml is uppercase bold continuation.
    letters = [ch for ch in next_plain if ch.isalpha()]
    return bool(letters) and all(ch.isupper() for ch in letters) and (
        first_plain.endswith("-") or first_inner.rstrip().endswith((" ", "\u00a0")) or re.search(r"-\s*</b>\s*$", first_inner, re.I) or next_plain == next_plain.upper()
    )


def _clean_html_document(
    doc_path: str,
    raw_html: str,
    book_title: str,
    running_headers: set[str],
    *,
    strip_pdftohtml: bool,
    extract_headings: bool,
    anchor_counter: List[int],
    extracted_headings: List[Tuple[str, str, str]],
) -> str:
    cleaned = TITLE_FILE_URI_RE.sub(rf"\1{html.escape(book_title)}\2", raw_html)
    cleaned = re.sub(
        r'\b((?:xml:)?lang\s*=\s*)(["\'])\s*\2',
        r"\1\g<2>en\g<2>",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = _upgrade_legacy_anchors_and_imgs(cleaned)

    if not strip_pdftohtml and not extract_headings:
        return cleaned

    if strip_pdftohtml:
        cleaned = re.sub(
            r"\s*<meta\b[^>]*pdftohtml[^>]*/?>", "", cleaned, flags=re.IGNORECASE
        )

    tokens: List[Tuple[bool, str, str, str, str]] = []
    # Token tuple: (is_p, open_tag_or_raw, inner, close_tag, plain)
    pos = 0
    for m in P_BLOCK_RE.finditer(cleaned):
        if m.start() > pos:
            tokens.append((False, cleaned[pos : m.start()], "", "", ""))
        tokens.append((True, m.group(1), m.group(2), m.group(3), ""))
        pos = m.end()
    if pos < len(cleaned):
        tokens.append((False, cleaned[pos:], "", "", ""))

    # Pass 1: clean footers, page counters, and running headers inside <p> tokens.
    processed: List[Tuple[bool, str, str, str, bool]] = []
    # (is_p, open_tag, inner, close_tag, stripped_footer)
    for is_p, head, inner, tail, _ in tokens:
        if not is_p:
            processed.append((False, head, "", "", False))
            continue

        stripped_footer = False
        new_inner = inner
        if strip_pdftohtml and FILE_URI_RE.search(new_inner):
            # Remove trailing file:///... (N of M)timestamp from paragraph end.
            updated = re.sub(
                r"\s*file:///[^\n<]+$", "", new_inner.rstrip(), flags=re.IGNORECASE
            )
            if updated != new_inner.rstrip():
                new_inner = updated
                stripped_footer = True

        plain_after = _strip_tags(new_inner)
        if strip_pdftohtml:
            if stripped_footer and not plain_after and "<img" not in new_inner.lower():
                processed.append((True, head, "", tail, True))
                continue
            if plain_after in running_headers:
                # Preserve running-header removal as stripped page break context.
                processed.append((True, head, "", tail, True))
                continue
            if not plain_after and "<img" not in new_inner.lower() and not stripped_footer:
                processed.append((True, head, new_inner, tail, False))
                continue

        processed.append((True, head, new_inner, tail, stripped_footer))

    # Pass 2: rejoin split sentences across removed footers & join split bold chapter headings.
    merged: List[Tuple[bool, str, str, str]] = []
    i = 0
    saw_break_since_last_p = False
    while i < len(processed):
        is_p, head, inner, tail, had_break = processed[i]
        if not is_p:
            if head.strip():
                saw_break_since_last_p = False
            merged.append((False, head, "", ""))
            i += 1
            continue

        plain = _strip_tags(inner)
        if not plain and "<img" not in inner.lower():
            if had_break:
                saw_break_since_last_p = True
            # Drop completely empty <p> left behind by stripped footers/headers or right after a break.
            if not had_break and not saw_break_since_last_p:
                merged.append((True, head, inner, tail))
            i += 1
            continue

        if strip_pdftohtml and saw_break_since_last_p and merged:
            # Find last non-empty <p> in merged.
            prev_idx = len(merged) - 1
            while prev_idx >= 0 and (
                (not merged[prev_idx][0] and not merged[prev_idx][1].strip())
                or (
                    merged[prev_idx][0]
                    and not _strip_tags(merged[prev_idx][2])
                    and "<img" not in merged[prev_idx][2].lower()
                )
            ):
                prev_idx -= 1
            if prev_idx >= 0 and merged[prev_idx][0]:
                prev_open, prev_inner, prev_close = (
                    merged[prev_idx][1],
                    merged[prev_idx][2],
                    merged[prev_idx][3],
                )
                prev_plain = _strip_tags(prev_inner)
                if _should_merge_continued_paragraph(prev_plain, plain):
                    joined_inner = prev_inner.rstrip() + " " + inner.lstrip()
                    merged[prev_idx] = (True, prev_open, joined_inner, prev_close)
                    del merged[prev_idx + 1 :]
                    saw_break_since_last_p = had_break
                    i += 1
                    continue

        saw_break_since_last_p = had_break

        # Merge two-line bold chapter heading split by pdftohtml.
        if strip_pdftohtml and CHAPTER_HEADING_RE.match(plain) and BOLD_ONLY_RE.match(inner):
            j = i + 1
            while j < len(processed) and (
                (not processed[j][0] and not processed[j][1].strip())
                or (
                    processed[j][0]
                    and not _strip_tags(processed[j][2])
                    and "<img" not in processed[j][2].lower()
                )
            ):
                j += 1
            if j < len(processed) and processed[j][0]:
                next_inner = processed[j][2]
                if _can_join_bold_heading(plain, inner, next_inner):
                    m1 = BOLD_ONLY_RE.match(inner)
                    m2 = BOLD_ONLY_RE.match(next_inner)
                    if m1 and m2:
                        combined_bold = f"<b{m1.group(1)}>{m1.group(2).rstrip()} {m2.group(2).lstrip()}</b>"
                        inner = combined_bold
                        plain = _strip_tags(inner)
                        saw_break_since_last_p = processed[j][4]
                        i = j

        merged.append((True, head, inner, tail))
        i += 1

    # Pass 3: attach XML ids to chapter headings if extracting headings for NCX.
    if extract_headings:
        pending_epilogue_only: Optional[Tuple[int, str]] = None
        for idx, (is_p, head, inner, tail) in enumerate(merged):
            if not is_p:
                continue
            plain = _strip_tags(inner)
            if not plain or len(plain) > 120 or not CHAPTER_HEADING_RE.match(plain):
                pending_epilogue_only = None
                continue

            anchor_m = re.search(r'\bid\s*=\s*(["\'])([^"\']+)\1', head)
            if anchor_m:
                anchor_id = anchor_m.group(2)
            else:
                anchor_counter[0] += 1
                anchor_id = f"ch_{anchor_counter[0]:03d}"
                head = head[:-1] + f' id="{anchor_id}">'
                merged[idx] = (True, head, inner, tail)

            # Combine bare "EPILOGUE" immediately followed by "CHAPTER N - Title".
            if plain.upper() == "EPILOGUE":
                pending_epilogue_only = (len(extracted_headings), anchor_id)
                extracted_headings.append((doc_path, anchor_id, plain))
                continue

            if (
                pending_epilogue_only is not None
                and plain.upper().startswith("CHAPTER ")
            ):
                prev_entry_idx, prev_anchor = pending_epilogue_only
                extracted_headings[prev_entry_idx] = (
                    doc_path,
                    prev_anchor,
                    f"EPILOGUE — {plain}",
                )
                pending_epilogue_only = None
                continue

            pending_epilogue_only = None
            extracted_headings.append((doc_path, anchor_id, plain))

    out_parts = [
        (item[1] if not item[0] else f"{item[1]}{item[2]}{item[3]}") for item in merged
    ]
    return "".join(out_parts)


def _html_has_target_id(raw_html: str, fragment: str) -> bool:
    escaped = re.escape(fragment)
    return bool(
        re.search(rf'\b(?:id|name)\s*=\s*(["\']){escaped}\1', raw_html)
    )


def _entries_from_toc_r1(
    toc_r1_path: str,
    ncx_path: str,
    cleaned_html: Dict[str, str],
) -> List[Tuple[str, str]]:
    toc_text = cleaned_html.get(toc_r1_path, "")
    toc_dir = posixpath.dirname(toc_r1_path)
    ncx_dir = posixpath.dirname(ncx_path)
    entries: List[Tuple[str, str]] = []
    seen_targets = set()

    for m in re.finditer(
        r'<a\b[^>]*\bhref\s*=\s*(["\'])([^"\']+)\1[^>]*>(.*?)</a>',
        toc_text,
        re.IGNORECASE | re.DOTALL,
    ):
        raw_href, raw_label = m.group(2), m.group(3)
        if raw_href.startswith(("http://", "https://", "mailto:")):
            continue
        label = _strip_tags(raw_label)
        if not label:
            continue
        path_part, _, frag_part = raw_href.partition("#")
        target_in_zip = posixpath.normpath(
            posixpath.join(toc_dir, path_part) if toc_dir else path_part
        )
        if target_in_zip not in cleaned_html:
            continue
        if frag_part and not _html_has_target_id(cleaned_html[target_in_zip], frag_part):
            frag_part = ""
        rel_href = posixpath.relpath(target_in_zip, ncx_dir) if ncx_dir else target_in_zip
        src_ref = f"{rel_href}#{frag_part}" if frag_part else rel_href
        if src_ref in seen_targets:
            continue
        seen_targets.add(src_ref)
        entries.append((label, src_ref))
    return entries


def _rebuild_ncx(
    ncx_path: str,
    ncx_text: str,
    book_title: str,
    nav_entries: List[Tuple[str, str]],
    *,
    opf_uid_value: str = "",
) -> str:
    updated = _set_ncx_dtb_uid(ncx_text, opf_uid_value) if opf_uid_value else ncx_text
    if "file:///" in updated.lower():
        updated = re.sub(
            r"(<docTitle>\s*<text>)[^<]+(</text>\s*</docTitle>)",
            rf"\1{html.escape(book_title)}\2",
            updated,
            flags=re.DOTALL,
        )

    if nav_entries:
        points = []
        for idx, (label, src_href) in enumerate(nav_entries, start=1):
            points.append(
                f'    <navPoint id="navPoint-{idx}" playOrder="{idx}">\n'
                f"      <navLabel>\n"
                f"        <text>{html.escape(label)}</text>\n"
                f"      </navLabel>\n"
                f'      <content src="{html.escape(src_href)}"/>\n'
                f"    </navPoint>"
            )
        new_navmap = "<navMap>\n" + "\n".join(points) + "\n  </navMap>"
        return re.sub(
            r"<navMap\b[^>]*>.*?</navMap>",
            new_navmap,
            updated,
            count=1,
            flags=re.DOTALL,
        )

    # Otherwise only fix invalid playOrder values (e.g., playOrder="0").
    order = [0]

    def _renumber(_match: re.Match[str]) -> str:
        order[0] += 1
        return f'playOrder="{order[0]}"'

    return re.sub(r'playOrder\s*=\s*(["\'])\d+\1', _renumber, updated)


def prepare_source_epub(
    book_or_title: Any,
    source_path: Path | str,
    prepared_dir: Optional[Path | str] = None,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Prepare a sanitized English EPUB under ``data/calibre/prepared`` if needed.

    The original Calibre file at ``source_path`` is strictly opened read-only.
    When no defects are detected, returns the original ``source_path`` unchanged.
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"source EPUB not found: {src}")

    title = _extract_title(book_or_title) or src.stem
    inspection = inspect_source_epub(src)
    if not inspection["needs_prep"]:
        return {
            "prepared": False,
            "path": str(src),
            "reason": "clean",
            "inspection": inspection,
        }

    dest = prepared_source_path(title, prepared_dir)
    if (
        not force
        and dest.exists()
        and dest.stat().st_size > 0
        and dest.stat().st_mtime >= src.stat().st_mtime
    ):
        return {
            "prepared": True,
            "cached": True,
            "path": str(dest),
            "inspection": inspection,
        }

    dest.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(src, "r") as zin:
        names = zin.namelist()
        raw_bytes = {name: zin.read(name) for name in names}

    opf_path = inspection["opf_path"]
    ncx_path = inspection["ncx_path"]
    opf_text = raw_bytes[opf_path].decode("utf-8", "ignore") if opf_path else ""
    ncx_text = raw_bytes[ncx_path].decode("utf-8", "ignore") if ncx_path else ""

    html_files = _html_entries_in_reading_order(names, opf_path, opf_text)
    removed_files = set(inspection["doc_outline_files"])
    kept_html_files = [h for h in html_files if h not in removed_files]

    html_raw = {h: raw_bytes[h].decode("utf-8", "ignore") for h in kept_html_files}
    strip_pdf = bool(
        inspection["pdftohtml"]
        or inspection["has_file_uri"]
        or inspection["has_page_footer"]
    )
    running_headers = _collect_running_headers(html_raw, title) if strip_pdf else set()
    extract_headings = bool(
        inspection["needs_ncx_rebuild"] and inspection["toc_r1_path"] is None
    )

    anchor_counter = [0]
    extracted_headings: List[Tuple[str, str, str]] = []
    cleaned_html: Dict[str, str] = {}
    for h in kept_html_files:
        cleaned_html[h] = _clean_html_document(
            h,
            html_raw[h],
            title,
            running_headers,
            strip_pdftohtml=strip_pdf,
            extract_headings=extract_headings,
            anchor_counter=anchor_counter,
            extracted_headings=extracted_headings,
        )

    opf_uid_value = ""
    if opf_path:
        opf_text = _remove_files_from_opf(opf_text, opf_path, sorted(removed_files))
        opf_text = _clean_opf_epub2_hygiene(opf_text)
        opf_text = _fix_opf_unique_identifier(opf_text)
        opf_uid_value = _extract_opf_uid_value(opf_text)

    if ncx_path:
        nav_entries: List[Tuple[str, str]] = []
        ncx_dir = posixpath.dirname(ncx_path)
        if inspection["toc_r1_path"] and inspection["needs_ncx_rebuild"]:
            nav_entries = _entries_from_toc_r1(
                inspection["toc_r1_path"], ncx_path, cleaned_html
            )
        elif extract_headings and extracted_headings:
            for doc_p, anchor_id, label in extracted_headings:
                rel = posixpath.relpath(doc_p, ncx_dir) if ncx_dir else doc_p
                nav_entries.append((label, f"{rel}#{anchor_id}"))
        ncx_text = _rebuild_ncx(
            ncx_path,
            ncx_text,
            title,
            nav_entries,
            opf_uid_value=opf_uid_value,
        )

    tmp_dest = dest.with_name(f".{dest.stem}.{os.getpid()}.tmp.epub")
    with zipfile.ZipFile(tmp_dest, "w") as zout:
        if "mimetype" in raw_bytes:
            zinfo = zipfile.ZipInfo("mimetype")
            zout.writestr(zinfo, raw_bytes["mimetype"], compress_type=zipfile.ZIP_STORED)
        for name in names:
            if name == "mimetype" or name in removed_files:
                continue
            if name in cleaned_html:
                data = cleaned_html[name].encode("utf-8")
            elif name == opf_path:
                data = opf_text.encode("utf-8")
            elif name == ncx_path:
                data = ncx_text.encode("utf-8")
            else:
                data = raw_bytes[name]
            zout.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)

    os.replace(tmp_dest, dest)
    return {
        "prepared": True,
        "cached": False,
        "path": str(dest),
        "removed_files": sorted(removed_files),
        "nav_entries_built": len(extracted_headings)
        if extract_headings
        else (len(nav_entries) if ncx_path and inspection["needs_ncx_rebuild"] else 0),
        "inspection": inspection,
    }
