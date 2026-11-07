"""Apply the reviewed Calibre metadata plans through the official calibredb CLI.

The script never writes metadata.db directly. It backs up the database first,
then calls `calibredb set_metadata` for each planned book. Default is dry-run;
pass --apply to write.

Usage:
    python scripts/literary/apply_calibre_metadata.py \
        --root literary-resources \
        --library-path "C:/Users/Bellussi/Biblioteca do calibre" \
        --backup-dir data/calibre/backup \
        --out data/calibre/metadata-apply-report.json \
        --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def find_calibredb() -> str:
    for candidate in (
        shutil.which("calibredb"),
        r"C:\Program Files\Calibre2\calibredb.exe",
        r"C:\Program Files\Calibre2\calibredb",
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("calibredb not found; install Calibre or add it to PATH")


def load_plans(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("metadata.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        author_sort = str(data.get("author_sort") or "").strip()
        for item in data.get("books") or []:
            if not item.get("calibre_id"):
                continue
            row = dict(item)
            row["_plan"] = path.relative_to(root).as_posix()
            if author_sort and not row.get("author_sort"):
                row["author_sort"] = author_sort
            rows.append(row)
    return rows


def read_rows(library: str, ids: List[int]) -> Dict[int, Dict[str, Any]]:
    db = os.path.join(library, "metadata.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    result: Dict[int, Dict[str, Any]] = {}
    for book_id in ids:
        row = con.execute("SELECT id, title, author_sort, series_index FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            continue
        series = con.execute(
            "SELECT s.name FROM books_series_link bsl JOIN series s ON s.id = bsl.series WHERE bsl.book = ?",
            (book_id,),
        ).fetchone()
        langs = [
            r["lang_code"]
            for r in con.execute(
                "SELECT l.lang_code FROM books_languages_link bll JOIN languages l ON l.id = bll.lang_code WHERE bll.book = ?",
                (book_id,),
            )
        ]
        result[book_id] = {
            "id": book_id,
            "title": row["title"],
            "author_sort": row["author_sort"],
            "series": series["name"] if series else "",
            "series_index": row["series_index"],
            "languages": langs,
        }
    con.close()
    return result


def build_fields(row: Dict[str, Any]) -> List[str]:
    fields = ["--field", f"title:{row['title']}"]
    if row.get("author_sort"):
        fields += ["--field", f"author_sort:{row['author_sort']}"]
    if row.get("series"):
        fields += ["--field", f"series:{row['series']}"]
    if row.get("series_index") is not None:
        fields += ["--field", f"series_index:{row['series_index']}"]
    if row.get("language"):
        fields += ["--field", f"languages:{row['language']}"]
    return fields


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="literary-resources")
    parser.add_argument("--library-path", required=True)
    parser.add_argument("--backup-dir", default="data/calibre/backup")
    parser.add_argument("--out", default="data/calibre/metadata-apply-report.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root)
    rows = load_plans(root)
    if not rows:
        print("No metadata plans found", file=sys.stderr)
        return 1
    ids = sorted({int(row["calibre_id"]) for row in rows})
    before = read_rows(args.library_path, ids)
    missing = [book_id for book_id in ids if book_id not in before]
    if missing:
        print(f"Calibre ids not found: {missing}", file=sys.stderr)
        return 1

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "library": os.path.abspath(args.library_path),
        "mode": "apply" if args.apply else "dry-run",
        "planned": len(rows),
        "backup": "",
        "before": before,
        "rows": [],
    }

    if args.apply:
        backup_dir = Path(args.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        db_backup = backup_dir / f"metadata-{stamp}.db"
        shutil.copy2(os.path.join(args.library_path, "metadata.db"), db_backup)
        report["backup"] = os.path.abspath(db_backup)
        prefs = os.path.join(args.library_path, "metadata_db_prefs_backup.json")
        if os.path.exists(prefs):
            shutil.copy2(prefs, backup_dir / f"metadata_db_prefs_backup-{stamp}.json")

    calibredb = find_calibredb()
    for row in rows:
        book_id = int(row["calibre_id"])
        fields = build_fields(row)
        command = [calibredb, "set_metadata", "--library-path", args.library_path, *fields, str(book_id)]
        entry = {
            "calibre_id": book_id,
            "plan": row["_plan"],
            "target": {
                "title": row["title"],
                "series": row.get("series", ""),
                "series_index": row.get("series_index"),
                "language": row.get("language", ""),
                "author_sort": row.get("author_sort", ""),
            },
            "command": subprocess.list2cmdline(command),
            "executed": False,
            "error": "",
        }
        if args.apply:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            entry["executed"] = result.returncode == 0
            entry["stdout"] = (result.stdout or "").strip()[-1000:]
            entry["stderr"] = (result.stderr or "").strip()[-1000:]
            if result.returncode != 0:
                entry["error"] = result.stderr or f"exit {result.returncode}"
        report["rows"].append(entry)

    after = read_rows(args.library_path, ids)
    report["after"] = after
    mismatches = []
    for row in rows:
        book_id = int(row["calibre_id"])
        current = after.get(book_id) or {}
        expected = {
            "title": row["title"],
            "series": row.get("series", ""),
            "series_index": row.get("series_index"),
            "languages": [row["language"]] if row.get("language") else [],
        }
        actual = {
            "title": current.get("title"),
            "series": current.get("series", ""),
            "series_index": current.get("series_index"),
            "languages": current.get("languages", []),
        }
        if expected["title"] != actual["title"] or expected["series"] != actual["series"]:
            mismatches.append({"calibre_id": book_id, "expected": expected, "actual": actual})
        elif expected["series_index"] is not None and float(expected["series_index"]) != float(actual["series_index"] or 0):
            mismatches.append({"calibre_id": book_id, "expected": expected, "actual": actual})
        elif expected["languages"] and expected["languages"][0] not in actual["languages"]:
            mismatches.append({"calibre_id": book_id, "expected": expected, "actual": actual})
    report["mismatches"] = mismatches
    report["ok"] = not mismatches and all(row.get("executed", True) for row in report["rows"])

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "mode": report["mode"],
        "planned": report["planned"],
        "backup": report["backup"],
        "executed": sum(1 for row in report["rows"] if row["executed"]),
        "mismatches": len(mismatches),
        "out": os.path.abspath(args.out),
    }, ensure_ascii=False, indent=2))
    return 0 if report["ok"] or not args.apply else 1


if __name__ == "__main__":
    sys.exit(main())
