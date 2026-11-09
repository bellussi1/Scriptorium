"""Score term/name probes against model output.

The probe files are built by ``scripts/build_eval_corpus.py``. For each probe,
the scorer checks every expected target against the model output and reports
per-occurrence term compliance, missing terms and name swaps. It does not need
the reference translation; when a reference is present it also reports chrF as
a secondary signal.

Usage:
    python scripts/score_probes.py --probes data/benchmark/literary/probes_*.jsonl \
        --run-dir data/benchmark/eval-dev --model index-translate-9b
    python scripts/score_probes.py --probes probes.jsonl --predictions run.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.literary.metrics import chrf  # noqa: E402


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").casefold()


def _contains(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    return _normalize(needle) in _normalize(haystack)


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
    candidates = []
    for path in run_dir.rglob(f"{model}.jsonl"):
        candidates.append(path)
    if not candidates:
        for path in run_dir.rglob("*.jsonl"):
            if model and model in path.stem:
                candidates.append(path)
    if not candidates:
        raise SystemExit(f"no prediction file for {model} under {run_dir}")
    # The newest run is the one that matters when the model was run repeatedly.
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    print(f"predictions: {path}", file=sys.stderr)
    return _read_jsonl([path])


def score(
    probes: Sequence[Dict[str, Any]],
    predictions: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    prediction_by_id = {str(row.get("id")): row for row in predictions if row.get("id")}
    per_probe = []
    by_kind: Dict[str, Counter] = defaultdict(Counter)
    by_series: Dict[str, Counter] = defaultdict(Counter)
    missing_examples: List[Dict[str, Any]] = []
    swap_examples: List[Dict[str, Any]] = []
    chrf_values: List[float] = []

    for probe in probes:
        probe_id = str(probe.get("id"))
        prediction = prediction_by_id.get(probe_id)
        output = _prediction_text(prediction) if prediction else ""
        expected = probe.get("expected_terms") or []
        characters = set(probe.get("characters") or [])
        pool = set(probe.get("character_pool") or [])
        term_hits = 0
        missing = []
        for term in expected:
            target = str(term.get("target") or "")
            if target and _contains(output, target):
                term_hits += 1
            else:
                missing.append({"source": term.get("source"), "target": target})
        name_hits = 0
        name_missing = []
        other_hits = []
        for name in characters:
            if _contains(output, name):
                name_hits += 1
            else:
                name_missing.append(name)
        for name in pool - characters:
            if _contains(output, name):
                other_hits.append(name)
        swap = bool(name_missing and other_hits)
        reference = str(probe.get("reference_pt") or "")
        chrf_value = None
        if reference and output:
            chrf_value = chrf(reference, output)
            chrf_values.append(chrf_value)
        kind = str(probe.get("kind") or "unknown")
        series = str(probe.get("series") or "unknown")
        for bucket in (by_kind[kind], by_series[series]):
            bucket["probes"] += 1
            bucket["term_total"] += len(expected)
            bucket["term_hit"] += term_hits
            bucket["name_total"] += len(characters)
            bucket["name_hit"] += name_hits
            bucket["swaps"] += 1 if swap else 0
            bucket["missing_probes"] += 1 if missing or name_missing else 0
        row = {
            "id": probe_id,
            "kind": kind,
            "series": series,
            "book": probe.get("book", ""),
            "term_total": len(expected),
            "term_hit": term_hits,
            "term_compliance": round(term_hits / len(expected), 4) if expected else None,
            "name_total": len(characters),
            "name_hit": name_hits,
            "name_compliance": round(name_hits / len(characters), 4) if characters else None,
            "name_swap": swap,
            "missing": missing,
            "name_missing": name_missing,
            "other_characters": other_hits,
            "chrf": chrf_value,
            "has_prediction": prediction is not None,
        }
        per_probe.append(row)
        if missing and len(missing_examples) < 40:
            missing_examples.append({"id": probe_id, "missing": missing})
        if swap and len(swap_examples) < 40:
            swap_examples.append(
                {"id": probe_id, "missing": name_missing, "other": other_hits}
            )

    def _summary(counter: Counter) -> Dict[str, Any]:
        term_total = counter["term_total"]
        name_total = counter["name_total"]
        return {
            "probes": counter["probes"],
            "term_total": term_total,
            "term_hit": counter["term_hit"],
            "term_compliance": round(counter["term_hit"] / term_total, 4) if term_total else None,
            "name_total": name_total,
            "name_hit": counter["name_hit"],
            "name_compliance": round(counter["name_hit"] / name_total, 4) if name_total else None,
            "swaps": counter["swaps"],
            "missing_probes": counter["missing_probes"],
        }

    overall = Counter({
        "probes": len(per_probe),
        "term_total": sum(row["term_total"] for row in per_probe),
        "term_hit": sum(row["term_hit"] for row in per_probe),
        "name_total": sum(row["name_total"] for row in per_probe),
        "name_hit": sum(row["name_hit"] for row in per_probe),
        "swaps": sum(1 for row in per_probe if row["name_swap"]),
        "missing_probes": sum(
            1 for row in per_probe if row["missing"] or row["name_missing"]
        ),
    })
    result = {
        "probes": len(probes),
        "predictions": len(predictions),
        "matched": sum(1 for row in per_probe if row["has_prediction"]),
        "summary": _summary(overall),
        "by_kind": {key: _summary(value) for key, value in sorted(by_kind.items())},
        "by_series": {key: _summary(value) for key, value in sorted(by_series.items())},
        "chrf_mean": round(sum(chrf_values) / len(chrf_values), 4) if chrf_values else None,
        "missing_examples": missing_examples,
        "swap_examples": swap_examples,
    }
    return result, per_probe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probes", nargs="+", required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--model", default="")
    parser.add_argument("--predictions", nargs="*", type=Path, default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--detail", type=Path)
    args = parser.parse_args()

    probes = _read_jsonl([Path(path) for path in args.probes])
    predictions = _load_predictions(
        run_dir=args.run_dir,
        model=args.model,
        predictions=[Path(path) for path in args.predictions],
    )
    result, per_probe = score(probes, predictions)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    if args.detail:
        args.detail.parent.mkdir(parents=True, exist_ok=True)
        args.detail.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in per_probe) + "\n",
            encoding="utf-8",
        )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
