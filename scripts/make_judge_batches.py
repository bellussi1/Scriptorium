"""Split a blind pairwise sheet into judge prompt batches.

The sheet is produced by ``scripts/make_pairwise_sheet.py``. This script writes
one plain-text prompt per batch plus a manifest with the item ids, so a judge
(Claude CLI, another model, or a human) can score the batches without seeing
the key. The expected JSON shape is the same one consumed by
``scripts/analyze_pairwise.py``.

Usage:
    python scripts/make_judge_batches.py \
      --sheet data/benchmark/eval-sun-eater-dev/judging.jsonl \
      --out-dir data/benchmark/eval-sun-eater-dev/claude-batches \
      --batch-size 14 --series "Sun Eater"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

HEADER = """You are an expert literary translator and editor specializing in English-to-Brazilian Portuguese fantasy and science fiction translation.

You will judge two candidate translations, A and B, of the same English excerpt. A published Brazilian Portuguese translation is provided as a reference for meaning and terminology, but it is not the only acceptable rendering. Do not reward mere copying of the reference.

Blind evaluation: do not try to guess which model produced which text. Judge only the text.

Score each candidate from 1 to 5:
5 = publishable: faithful, natural Brazilian Portuguese, preserves voice, register, rhythm and dialogue, correct terminology, no meaning errors.
4 = strong: minor awkwardness or a small loss of nuance, no substantive errors.
3 = acceptable: meaning mostly intact, but noticeable calque, literalness, rhythm problems or terminology inconsistency.
2 = weak: meaning errors, omissions or additions, unnatural syntax, inconsistent names or terms, but still readable.
1 = bad: broken, truncated, hallucinated, untranslated, or incomprehensible.

Preference: "a", "b" or "tie". Use "tie" only when the two are effectively equivalent. If one has a meaning or terminology error, the other wins even if it is slightly less elegant.

Pay special attention to fidelity to the source, naturalness in Brazilian Portuguese, literary voice, dialogue register, consistent names and terms{hint}, English leakage, invented facts, and gender agreement.

Return ONLY a JSON array with one object per item, in this exact shape:
{{"id": "...", "score_a": 1, "score_b": 1, "preference": "a", "notes": "one short sentence in Portuguese"}}

Do not use markdown fences. Do not add commentary before or after the array.
"""


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=14)
    parser.add_argument("--series", default="")
    parser.add_argument(
        "--hint",
        default="",
        help="Optional comma-separated examples appended to the terminology sentence.",
    )
    args = parser.parse_args()

    rows = _read_jsonl(args.sheet)
    if not rows:
        raise SystemExit("empty sheet")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    hint = f" (for example {args.hint})" if args.hint.strip() else ""
    batches = [rows[index:index + args.batch_size] for index in range(0, len(rows), args.batch_size)]
    manifest = {"sheet": str(args.sheet), "series": args.series, "batches": []}
    for number, batch in enumerate(batches, start=1):
        lines = [HEADER.format(hint=hint)]
        if args.series:
            lines.append(f"Series: {args.series}\n")
        for position, row in enumerate(batch, start=1):
            lines.extend(
                [
                    f"ITEM {position}",
                    f"id: {row['id']}",
                    f"book: {row.get('book', '')}",
                    f"category: {row.get('category', '')}",
                    "",
                    "SOURCE:",
                    row.get("source", "").strip(),
                    "",
                    "REFERENCE PT:",
                    (row.get("reference_pt") or "").strip(),
                    "",
                    "A:",
                    (row.get("output_a") or "").strip(),
                    "",
                    "B:",
                    (row.get("output_b") or "").strip(),
                    "",
                    "",
                ]
            )
        path = args.out_dir / f"batch-{number:02d}.txt"
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        manifest["batches"].append(
            {"file": str(path), "items": [str(row["id"]) for row in batch], "count": len(batch)}
        )
        print(f"{path}: {len(batch)} items")
    manifest_path = args.out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
