"""Build a standardized Kindle-ready folder from completed queue artifacts.

The queue database remains the source of truth. This module copies the best
available EPUB for each book into::

    translated_files/kindle/<Author>/<Series>/<index> - <Title> (pt-BR).epub

and writes series metadata, reading-order tags, language, translator role and a
manifest. The source EPUBs are never modified.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .epub import read_epub, update_opf_metadata
from .queue import QueueStore


def _safe(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]', "", str(value or "")).strip().strip(".")
    return value or "Unknown"


def author_sort(author: str) -> str:
    parts = str(author or "").strip().split()
    if len(parts) < 2:
        return str(author or "").strip()
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def index_label(series_index: Optional[float]) -> str:
    if series_index is None:
        return "00"
    text = f"{series_index:g}"
    if "." not in text:
        return text.zfill(2)
    whole, fraction = text.split(".", 1)
    return f"{whole.zfill(2)}.{fraction}"


def tags_for(book: Any) -> List[str]:
    author = str(getattr(book, "author", "") or "").casefold()
    series = str(getattr(book, "series", "") or "")
    tags = ["Brazilian Portuguese", "Machine Translation"]
    if "hobb" in author:
        tags.extend(["Fantasy", "Epic Fantasy"])
    elif "ruocchio" in author:
        tags.extend(["Science Fiction", "Space Opera"])
    elif "mcmurtry" in author:
        tags.extend(["Western", "Literary Fiction"])
    else:
        tags.append("Literary Fiction")
    if series:
        tags.append(series)
    return list(dict.fromkeys(tags))


def _artifact_rank(filename: str, title: str) -> int:
    safe_title = _safe(title)
    if not filename.startswith(f"{safe_title} (pt-BR)") or not filename.endswith(".epub"):
        return 0
    if filename.endswith(".refined.epub"):
        return 4
    if filename.endswith(" - fixed-v2.epub"):
        return 3
    if filename.endswith(" - fixed.epub"):
        return 2
    return 1


def best_artifact(outputs_dir: Path, title: str) -> Optional[Path]:
    if not outputs_dir.exists():
        return None
    candidates = [
        (rank, path)
        for path in outputs_dir.iterdir()
        if path.is_file()
        for rank in [_artifact_rank(path.name, title)]
        if rank
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1].stat().st_mtime))[1]


def _description(title: str) -> str:
    return (
        f"Edição em português brasileiro de {title}. "
        "Tradução assistida por IA; revisão editorial recomendada."
    )


def build_kindle_library(
    *,
    db_path: str = "data/literary_queue.db",
    outputs_dir: str = "translated_files",
    output_root: str = "translated_files/kindle",
    include_needs_review: bool = True,
) -> Dict[str, Any]:
    outputs = Path(outputs_dir)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    store = QueueStore(db_path)
    books = store.list_books(limit=500)
    store.close()

    manifest: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    for book in books:
        artifact = best_artifact(outputs, book.title)
        if artifact is None:
            skipped.append({"title": book.title, "reason": "no artifact"})
            continue
        allowed_states = {"completed"}
        if include_needs_review:
            allowed_states.add("needs_review")
        if book.status not in allowed_states:
            skipped.append({"title": book.title, "reason": book.status})
            continue
        info = read_epub(str(artifact), include_text=False)
        translated_title = info.title or book.title
        author = book.author or "Unknown"
        series = book.series or "Standalone"
        destination = (
            root
            / _safe(author)
            / _safe(series)
            / f"{index_label(book.series_index)} - {_safe(book.title)} (pt-BR).epub"
        )
        update_opf_metadata(
            str(artifact),
            str(destination),
            title=translated_title,
            language="pt-BR",
            series=series if book.series else None,
            series_index=book.series_index if book.series else None,
            subjects=tags_for(book),
            description=_description(book.title),
            translator="TranslateBook with LLM (TBL)",
            title_sort=translated_title,
            author_sort=author_sort(author),
        )
        manifest.append(
            {
                "book_id": book.id,
                "title": book.title,
                "translated_title": translated_title,
                "author": author,
                "series": series,
                "series_index": book.series_index,
                "status": book.status,
                "artifact": artifact.name,
                "file": str(destination.relative_to(root)),
            }
        )

    manifest_path = root / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()) if manifest else ["book_id"])
        writer.writeheader()
        writer.writerows(manifest)

    readme = root / "README.md"
    lines = [
        "# Kindle library",
        "",
        "Generated from the persistent literary queue. EPUB files are in reading",
        "order; series name, index, language, translator role and tags are embedded",
        "in the OPF metadata.",
        "",
        "| # | Series | Title | File | Status |",
        "|---:|---|---|---|---|",
    ]
    ordered = sorted(
        manifest,
        key=lambda item: (
            str(item["author"]).casefold(),
            str(item["series"]).casefold(),
            item["series_index"] or 0,
        ),
    )
    for index, item in enumerate(ordered, start=1):
        lines.append(
            f"| {index} | {item['series']} #{index_label(item['series_index'])} | "
            f"{item['title']} | `{item['file']}` | {item['status']} |"
        )
    lines.extend(
        [
            "",
            "Machine translation is a draft. Read before publishing; the queue",
            "records the validation and refinement report for each book.",
        ]
    )
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "root": str(root),
        "books": len(manifest),
        "skipped": skipped,
        "manifest": str(manifest_path),
        "readme": str(readme),
        "files": [item["file"] for item in manifest],
    }
