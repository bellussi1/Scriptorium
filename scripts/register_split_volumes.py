"""Register the volumes produced by ``split_omnibus.py`` as completed queue books.

A split omnibus is one translation job but several reading units. The Kindle
export and the Files tab work per queue book, so each volume needs its own row
pointing at its own source slice and artifact.

By default the script only prints the plan; pass ``--apply`` to write the rows.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.literary.epub import read_epub  # noqa: E402
from src.literary.queue import hash_config, hash_file  # noqa: E402


def _load_manifest(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _by_index(items: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {int(item["index"]): item for item in items}


def build_plan(
    *,
    translations: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    series: str,
    author: str,
    calibre_id: int,
    glossary_scope: str,
    provider: str,
    model: str,
) -> List[Dict[str, Any]]:
    source_by_index = _by_index(sources)
    plan: List[Dict[str, Any]] = []
    for item in translations:
        index = int(item["index"])
        source = source_by_index.get(index)
        if source is None:
            raise SystemExit(f"no source slice for volume {index}")
        artifact = Path(item["path"])
        source_path = Path(source["path"])
        if not artifact.is_file():
            raise SystemExit(f"artifact missing: {artifact}")
        if not source_path.is_file():
            raise SystemExit(f"source slice missing: {source_path}")
        info = read_epub(str(source_path), include_text=True)
        plan.append(
            {
                "index": index,
                "title": str(source["title"]),
                "display_title": str(item["title"]),
                "artifact": artifact,
                "source_path": source_path,
                "source_hash": hash_file(str(source_path)),
                "config_hash": hash_config(
                    {
                        "provider": provider,
                        "model": model,
                        "glossary": glossary_scope,
                        "style": glossary_scope,
                        "split_index": index,
                    }
                ),
                "word_count": int(info.word_count or 0),
                "series": series,
                "series_index": float(index),
                "author": author,
                "calibre_id": calibre_id,
                "glossary_scope": glossary_scope,
                "provider": provider,
                "model": model,
            }
        )
    return plan


def apply_plan(db_path: Path, plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    applied: List[Dict[str, Any]] = []
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        for entry in plan:
            existing = connection.execute(
                "SELECT id, status FROM books WHERE calibre_id = ? AND source_path = ?",
                (entry["calibre_id"], str(entry["source_path"])),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE books
                       SET title = ?, author = ?, series = ?, series_index = ?,
                           word_count = ?, status = 'completed', priority = 0,
                           glossary_scope = ?, model = ?, provider = ?,
                           actual_cost = 0, estimated_cost = 0,
                           source_hash = ?, config_hash = ?,
                           updated_at = ?, reviewed_at = ?
                     WHERE id = ?
                    """,
                    (
                        entry["title"],
                        entry["author"],
                        entry["series"],
                        entry["series_index"],
                        entry["word_count"],
                        entry["glossary_scope"],
                        entry["model"],
                        entry["provider"],
                        entry["source_hash"],
                        entry["config_hash"],
                        now,
                        now,
                        int(existing["id"]),
                    ),
                )
                book_id = int(existing["id"])
                action = f"updated from {existing['status']}"
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO books (
                        calibre_id, source_path, title, author, series, series_index,
                        source_language, target_language, word_count, status, priority,
                        glossary_scope, style_scope, model, provider, estimated_cost,
                        actual_cost, source_hash, config_hash, created_at, updated_at,
                        reviewed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'eng', 'pt-BR', ?, 'completed', 0,
                              ?, '', ?, ?, 0, 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry["calibre_id"],
                        str(entry["source_path"]),
                        entry["title"],
                        entry["author"],
                        entry["series"],
                        entry["series_index"],
                        entry["word_count"],
                        entry["glossary_scope"],
                        entry["model"],
                        entry["provider"],
                        entry["source_hash"],
                        entry["config_hash"],
                        now,
                        now,
                        now,
                    ),
                )
                book_id = int(cursor.lastrowid)
                action = "inserted"
            connection.execute(
                "INSERT INTO events (book_id, level, message, created_at) VALUES (?, 'info', ?, ?)",
                (
                    book_id,
                    f"split volume {entry['index']} ({entry['display_title']}) registered as completed",
                    now,
                ),
            )
            applied.append({**entry, "book_id": book_id, "action": action})
        connection.commit()
    finally:
        connection.close()
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="split-manifest.json of the translation")
    parser.add_argument("--sources-manifest", required=True, help="split-manifest.json of the source slices")
    parser.add_argument("--db", default="data/literary_queue.db")
    parser.add_argument("--series", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--calibre-id", type=int, required=True)
    parser.add_argument("--glossary-scope", default="")
    parser.add_argument("--provider", default="gemini")
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    plan = build_plan(
        translations=_load_manifest(Path(args.manifest)),
        sources=_load_manifest(Path(args.sources_manifest)),
        series=args.series,
        author=args.author,
        calibre_id=args.calibre_id,
        glossary_scope=args.glossary_scope,
        provider=args.provider,
        model=args.model,
    )
    for entry in plan:
        print(
            f"[{entry['index']:02d}] {entry['display_title']} -> {entry['artifact'].name} "
            f"(queue title {entry['title']!r}, {entry['word_count']:,} words)"
        )
    if not args.apply:
        print("dry run: pass --apply to write the rows")
        return 0
    applied = apply_plan(Path(args.db), plan)
    for entry in applied:
        print(f"[{entry['index']:02d}] book {entry['book_id']}: {entry['action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
