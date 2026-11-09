"""Reference-based COMET scoring for a corpus run.

COMET is a second automatic metric next to chrF. It is optional and heavy:
``unbabel-comet`` pulls PyTorch and the first run downloads the checkpoint.
Install it in a separate environment and run on CPU after generation:

    python -m pip install -r requirements-comet.txt
    python scripts/score_comet.py --corpus data/benchmark/literary/eval_farseer_dev.jsonl \
        --run-dir data/benchmark/eval-dev --model index-translate-9b \
        --out data/benchmark/eval-dev/comet.json

The long chapters can be scored too, but COMET truncates very long inputs; use
the chunked long-context runner before drawing conclusions from them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read_jsonl(paths: Sequence[Path]) -> List[Dict[str, Any]]:
    rows = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _prediction_text(row: Dict[str, Any]) -> str:
    generation = row.get("generation")
    if isinstance(generation, dict):
        return str(generation.get("text") or "")
    return str(row.get("text") or row.get("output") or "")


def _load_predictions(
    *,
    run_dir: Optional[Path],
    model: str,
    predictions: Sequence[Path],
) -> List[Dict[str, Any]]:
    if predictions:
        return _read_jsonl(predictions)
    if run_dir is None:
        raise SystemExit("pass --predictions or --run-dir")
    candidates = list(run_dir.rglob(f"{model}.jsonl"))
    if not candidates:
        candidates = [path for path in run_dir.rglob("*.jsonl") if model and model in path.stem]
    if not candidates:
        raise SystemExit(f"no prediction file for {model} under {run_dir}")
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    print(f"predictions: {path}", file=sys.stderr)
    return _read_jsonl([path])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--model", default="")
    parser.add_argument("--predictions", nargs="*", type=Path, default=[])
    parser.add_argument("--model-name", default="Unbabel/wmt22-comet-da")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    try:
        from comet import download_model, load_from_checkpoint
    except ImportError:
        print(
            "COMET is not installed. Install the optional environment:\n"
            "  python -m pip install -r requirements-comet.txt\n"
            "The first run downloads the checkpoint and can be run on CPU.",
            file=sys.stderr,
        )
        return 2

    corpus = _read_jsonl([args.corpus])
    predictions = _load_predictions(
        run_dir=args.run_dir,
        model=args.model,
        predictions=[Path(path) for path in args.predictions],
    )
    prediction_by_id = {str(row.get("id")): row for row in predictions if row.get("id")}
    data = []
    items = []
    for row in corpus:
        reference = str(row.get("reference_pt") or "")
        if not reference:
            continue
        prediction = prediction_by_id.get(str(row.get("id")))
        if prediction is None:
            continue
        hypothesis = _prediction_text(prediction)
        if not hypothesis:
            continue
        data.append({"src": str(row.get("text") or ""), "ref": reference, "mt": hypothesis})
        items.append(
            {
                "id": row.get("id"),
                "book": row.get("book", ""),
                "category": row.get("category", ""),
                "hypothesis_chars": len(hypothesis),
                "reference_chars": len(reference),
            }
        )
        if args.limit and len(data) >= args.limit:
            break
    if not data:
        print("no paired source/reference/hypothesis rows", file=sys.stderr)
        return 1

    print(f"loading COMET checkpoint {args.model_name}...", file=sys.stderr)
    model_path = download_model(args.model_name)
    model = load_from_checkpoint(model_path)
    # COMET expects gpus=0 for CPU. Some versions use a different argument;
    # fall back to the default if the keyword is rejected.
    try:
        output = model.predict(data, batch_size=args.batch_size, gpus=0)
    except TypeError:
        output = model.predict(data, batch_size=args.batch_size)
    if isinstance(output, dict):
        scores = list(output.get("scores") or [])
        system_score = output.get("system_score")
    else:
        scores = list(getattr(output, "scores", []) or [])
        system_score = getattr(output, "system_score", None)
    for item, score in zip(items, scores):
        item["comet"] = round(float(score), 4)
    result = {
        "model_name": args.model_name,
        "rows": len(items),
        "system_score": round(float(system_score), 4) if system_score is not None else None,
        "mean_item_score": round(sum(scores) / len(scores), 4) if scores else None,
        "items": items,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
