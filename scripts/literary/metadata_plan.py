"""Build a dry-run Calibre metadata correction plan for Sun Eater.

This script never writes to Calibre. It prints the fields and the exact
`calibredb set_metadata` commands; the user must review and authorize them.

Usage:
    python scripts/literary/metadata_plan.py \
        --inventory data/calibre/targets.json \
        --plan literary-resources/christopher-ruocchio/sun-eater/metadata.yaml \
        --out data/calibre/sun-eater-metadata-plan.json
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

import yaml


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--library", default=r"C:\Users\Bellussi\Biblioteca do calibre")
    args = parser.parse_args(argv)

    plan = yaml.safe_load(Path(args.plan).read_text(encoding="utf-8"))
    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    by_id = {int(book["calibre_id"]): book for book in inventory.get("books", [])}
    rows = []
    for item in plan.get("books", []):
        calibre_id = int(item["calibre_id"])
        current = by_id.get(calibre_id, {})
        fields = [
            f"series:{item['series']}",
            f"series_index:{item['series_index']}",
            f"title:{item['title']}",
            f"languages:{item['language']}",
        ]
        command = [
            "calibredb",
            "set_metadata",
            "--library-path",
            args.library,
            *sum((["--field", field] for field in fields), []),
            str(calibre_id),
        ]
        rows.append(
            {
                "calibre_id": calibre_id,
                "current_title": current.get("title", ""),
                "current_series": current.get("series", ""),
                "current_series_index": current.get("series_index"),
                "current_languages": current.get("languages", []),
                "target_title": item["title"],
                "target_series": item["series"],
                "target_series_index": item["series_index"],
                "target_language": item["language"],
                "note": item.get("note", ""),
                "command": " ".join(shlex.quote(part) for part in command),
                "executed": False,
            }
        )
    payload = {
        "status": "dry-run",
        "warning": "Do not run these commands without explicit approval. Back up the Calibre library first.",
        "library": args.library,
        "rows": rows,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(json.dumps({"out": os.path.abspath(args.out), "rows": len(rows)}, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
