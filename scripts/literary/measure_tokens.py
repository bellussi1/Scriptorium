"""Measure real token/word ratios on local sample chapters.

Usage:
    python scripts/literary/measure_tokens.py data/editorial_samples
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import tiktoken

WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019\-][^\W\d_]+)*", re.UNICODE)


def measure(path: Path, encoder) -> dict:
    text = path.read_text(encoding="utf-8")
    words = len(WORD_RE.findall(text))
    tokens = len(encoder.encode(text))
    return {
        "file": str(path),
        "words": words,
        "tokens": tokens,
        "tokens_per_word": round(tokens / words, 4) if words else 0,
        "chars": len(text),
    }


def main(root: str) -> int:
    encoder = tiktoken.get_encoding("cl100k_base")
    rows = []
    for path in sorted(Path(root).rglob("*.txt")):
        if path.name == "manifest.json":
            continue
        row = measure(path, encoder)
        row["book"] = path.parent.name
        rows.append(row)
    by_book: dict[str, list[dict]] = {}
    for row in rows:
        by_book.setdefault(row["book"], []).append(row)
    summary = []
    for book, items in sorted(by_book.items()):
        words = sum(item["words"] for item in items)
        tokens = sum(item["tokens"] for item in items)
        summary.append(
            {
                "book": book,
                "files": len(items),
                "words": words,
                "tokens": tokens,
                "tokens_per_word": round(tokens / words, 4) if words else 0,
            }
        )
    print(json.dumps({"summary": summary, "files": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/editorial_samples"))
