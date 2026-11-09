"""Build a blind pairwise judging sheet from two model run files.

The sheet hides the model identity behind A/B and stores the key separately.
The judge fills ``score_a``, ``score_b`` (1-5), ``preference`` (a/b/tie) and
``notes``; ``scripts/analyze_pairwise.py`` computes the statistics.

Usage:
    python scripts/make_pairwise_sheet.py \
      --corpus data/benchmark/literary/eval_farseer_dev.jsonl \
      --run-dir data/benchmark/eval-dev --model-a hy-mt2-7b \
      --model-b index-translate-9b --out data/benchmark/eval-dev/judging.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _find_model_file(run_dir: Path, model: str) -> Path:
    candidates = list(run_dir.rglob(f"{model}.jsonl"))
    if not candidates:
        raise SystemExit(f"no {model}.jsonl under {run_dir}")
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _text(row: Dict[str, Any]) -> str:
    generation = row.get("generation")
    if isinstance(generation, dict):
        return str(generation.get("text") or "")
    return str(row.get("text") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model-a", required=True)
    parser.add_argument("--model-b", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    corpus = {str(row["id"]): row for row in _read_jsonl(args.corpus)}
    file_a = _find_model_file(args.run_dir, args.model_a)
    file_b = _find_model_file(args.run_dir, args.model_b)
    rows_a = {str(row["id"]): _text(row) for row in _read_jsonl(file_a)}
    rows_b = {str(row["id"]): _text(row) for row in _read_jsonl(file_b)}
    rng = random.Random(args.seed)
    sheet = []
    key = {}
    for item_id, source_row in corpus.items():
        if item_id not in rows_a or item_id not in rows_b:
            continue
        swap = rng.random() < 0.5
        output_a = rows_b[item_id] if swap else rows_a[item_id]
        output_b = rows_a[item_id] if swap else rows_b[item_id]
        sheet.append(
            {
                "id": item_id,
                "book": source_row.get("book", ""),
                "category": source_row.get("category", ""),
                "source": source_row.get("text", ""),
                "reference_pt": source_row.get("reference_pt", ""),
                "output_a": output_a,
                "output_b": output_b,
                "score_a": None,
                "score_b": None,
                "preference": "",
                "notes": "",
            }
        )
        key[item_id] = {
            "a": args.model_b if swap else args.model_a,
            "b": args.model_a if swap else args.model_b,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in sheet) + "\n",
        encoding="utf-8",
    )
    key_path = args.key or args.out.with_name(args.out.stem + "-key.json")
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sheet": str(args.out), "key": str(key_path), "rows": len(sheet)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
