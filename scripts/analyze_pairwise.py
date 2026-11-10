"""Pairwise statistics for blind model judgments.

The judge fills a sheet with ``score_a``, ``score_b`` (1-5) and ``preference``
(``a``, ``b`` or ``tie``). Because ``make_pairwise_sheet.py`` randomizes which
model sits in column A for each excerpt, pass ``--key`` and
``--reference-model`` to normalize every row to the same model before
computing wins. Without that normalization, ``wins_a`` mixes both models and is
not a model win rate.

Reports win rate, mean score difference, paired bootstrap confidence intervals
(row-level and clustered by book) and an exact sign test. It does not need
scipy.

Usage:
    python scripts/analyze_pairwise.py \
      --input data/benchmark/eval-dev/judging.jsonl \
      --key data/benchmark/eval-dev/judging-key.json \
      --reference-model index-translate-9b
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _percentile(values: List[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _load_key(path: Path) -> Dict[str, Dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object mapping ids to A/B models")
    key: Dict[str, Dict[str, str]] = {}
    for item_id, mapping in data.items():
        if not isinstance(mapping, dict) or "a" not in mapping or "b" not in mapping:
            raise ValueError(f"invalid A/B mapping for {item_id!r}")
        key[str(item_id)] = {"a": str(mapping["a"]), "b": str(mapping["b"])}
    return key


def _normalize_rows(
    rows: List[Dict[str, Any]],
    key: Optional[Dict[str, Dict[str, str]]],
    reference_model: Optional[str],
) -> List[Dict[str, Any]]:
    """Put ``reference_model`` in column A for every scored row.

    A row whose key says the reference model was shown as B gets its scores
    swapped and its preference flipped. Rows without both scores are left out
    because they were not judged yet.
    """
    if key is None:
        return [row for row in rows if row.get("score_a") is not None and row.get("score_b") is not None]
    if not reference_model:
        raise ValueError("--reference-model is required when --key is given")

    normalized: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("score_a") is None or row.get("score_b") is None:
            continue
        item_id = str(row.get("id") or "")
        mapping = key.get(item_id)
        if mapping is None:
            raise ValueError(f"key has no A/B mapping for {item_id!r}")
        a_model = mapping["a"]
        b_model = mapping["b"]
        if a_model == reference_model and b_model != reference_model:
            normalized.append(dict(row))
        elif b_model == reference_model and a_model != reference_model:
            flipped = dict(row)
            flipped["score_a"], flipped["score_b"] = row["score_b"], row["score_a"]
            preference = str(row.get("preference") or "").lower()
            flipped["preference"] = {"a": "b", "b": "a"}.get(preference, preference)
            normalized.append(flipped)
        else:
            raise ValueError(
                f"row {item_id!r} maps to {a_model!r}/{b_model!r}, "
                f"which does not identify {reference_model!r} on exactly one side"
            )
    return normalized


def _preference(row: Dict[str, Any]) -> str:
    preference = str(row.get("preference") or "").lower()
    if preference in {"a", "b", "tie"}:
        return preference
    score_a = float(row["score_a"])
    score_b = float(row["score_b"])
    if score_a > score_b:
        return "a"
    if score_b > score_a:
        return "b"
    return "tie"


def _summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "items": 0,
            "wins_a": 0,
            "wins_b": 0,
            "ties": 0,
            "mean_score_a": None,
            "mean_score_b": None,
            "mean_diff_a_minus_b": None,
        }
    scores_a = [float(row["score_a"]) for row in rows]
    scores_b = [float(row["score_b"]) for row in rows]
    preferences = [_preference(row) for row in rows]
    return {
        "items": len(rows),
        "wins_a": preferences.count("a"),
        "wins_b": preferences.count("b"),
        "ties": preferences.count("tie"),
        "mean_score_a": round(statistics.mean(scores_a), 4),
        "mean_score_b": round(statistics.mean(scores_b), 4),
        "mean_diff_a_minus_b": round(statistics.mean([a - b for a, b in zip(scores_a, scores_b)]), 4),
    }


def _bootstrap(
    rows: List[Dict[str, Any]],
    *,
    iterations: int = 10000,
    seed: int = 17,
    cluster_field: Optional[str] = None,
) -> Dict[str, Any]:
    if not rows:
        return {}
    rng = random.Random(seed)
    clusters: List[List[int]] = []
    if cluster_field:
        grouped: Dict[str, List[int]] = defaultdict(list)
        for index, row in enumerate(rows):
            grouped[str(row.get(cluster_field) or "unknown")].append(index)
        clusters = list(grouped.values())
    else:
        clusters = [[index] for index in range(len(rows))]

    mean_diffs: List[float] = []
    win_rates: List[float] = []
    for _ in range(iterations):
        sample: List[int] = []
        for _ in range(len(clusters)):
            sample.extend(rng.choice(clusters))
        scores_a = [float(rows[index]["score_a"]) for index in sample]
        scores_b = [float(rows[index]["score_b"]) for index in sample]
        preferences = [_preference(rows[index]) for index in sample]
        wins = preferences.count("a")
        losses = preferences.count("b")
        mean_diffs.append(statistics.mean([a - b for a, b in zip(scores_a, scores_b)]))
        win_rates.append(wins / (wins + losses) if wins + losses else 0.5)
    return {
        "mean_diff_ci95": [round(_percentile(mean_diffs, 0.025), 4), round(_percentile(mean_diffs, 0.975), 4)],
        "win_rate_ci95": [round(_percentile(win_rates, 0.025), 4), round(_percentile(win_rates, 0.975), 4)],
        "iterations": iterations,
        "clusters": len(clusters),
    }


def _sign_test(wins: int, losses: int) -> Optional[float]:
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 4)


def analyze(
    rows: List[Dict[str, Any]],
    key: Optional[Dict[str, Dict[str, str]]] = None,
    reference_model: Optional[str] = None,
) -> Dict[str, Any]:
    scored = _normalize_rows(rows, key, reference_model)
    opponents = set()
    if key is not None:
        for row in scored:
            mapping = key[str(row["id"])]
            for model in (mapping["a"], mapping["b"]):
                if model != reference_model:
                    opponents.add(model)
    model_a = reference_model or "A"
    model_b = next(iter(opponents)) if len(opponents) == 1 else ("mixed" if opponents else "B")

    summary = _summary(scored)
    preferences = [_preference(row) for row in scored]
    wins_a = preferences.count("a")
    wins_b = preferences.count("b")
    decisive = wins_a + wins_b
    result: Dict[str, Any] = {
        "items": len(rows),
        "scored": len(scored),
        "normalized": key is not None,
        "model_a": model_a,
        "model_b": model_b,
        **summary,
        "win_rate_a_decisive": round(wins_a / decisive, 4) if decisive else None,
        "win_rate_a_all": round(wins_a / len(scored), 4) if scored else None,
        "sign_test_p": _sign_test(wins_a, wins_b),
        "bootstrap": _bootstrap(scored, iterations=10000, seed=17),
        "bootstrap_by_book": _bootstrap(scored, iterations=10000, seed=17, cluster_field="book"),
    }

    by_category: Dict[str, Any] = {}
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in scored:
        groups[str(row.get("category") or "unknown")].append(row)
    for category, group in sorted(groups.items()):
        by_category[category] = _summary(group)
    result["by_category"] = by_category

    by_book: Dict[str, Any] = {}
    book_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in scored:
        book_groups[str(row.get("book") or "unknown")].append(row)
    for book, group in sorted(book_groups.items()):
        by_book[book] = _summary(group)
    result["by_book"] = by_book

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--reference-model", help="Model to report as A; required with --key")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.key and not args.reference_model:
        raise SystemExit("--reference-model is required when --key is given")
    key = _load_key(args.key) if args.key else None
    rows = _read_jsonl(args.input)
    result = analyze(rows, key=key, reference_model=args.reference_model)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
