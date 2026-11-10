"""Run a Claude judge over blind A/B prompt batches.

One-off evaluation helper. Reads every batch-*.txt in a directory, sends it to
the Claude CLI with tools disabled, extracts the JSON array, and writes one
judgments JSONL plus the raw responses for audit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batches", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--model", default="sonnet")
    args = parser.parse_args()

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for batch in sorted(args.batches.glob("batch-*.txt")):
        prompt = batch.read_text(encoding="utf-8")
        completed = subprocess.run(
            ["claude", "-p", "--bare", "--tools=", "--model", args.model],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        (args.raw_dir / f"{batch.stem}-raw.txt").write_text(output, encoding="utf-8")
        if completed.returncode != 0:
            raise SystemExit(f"{batch.name}: exit {completed.returncode}: {output[-800:]}")
        start = output.find("[")
        end = output.rfind("]")
        if start < 0 or end < start:
            raise SystemExit(f"{batch.name}: no JSON array in output: {output[-800:]}")
        payload = json.loads(output[start : end + 1])
        if not isinstance(payload, list):
            raise SystemExit(f"{batch.name}: JSON is not an array")
        rows.extend(payload)
        print(f"{batch.name}: {len(payload)} items", flush=True)
    args.out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    print(f"{args.out}: {len(rows)} judgments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
