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
from dataclasses import dataclass, field
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
