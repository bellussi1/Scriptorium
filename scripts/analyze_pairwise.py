"""Pairwise statistics for blind model judgments.

The judge fills a sheet with ``score_a``, ``score_b`` (1-5) and ``preference``
(``a``, ``b`` or ``tie``). This script reports win rate, mean score difference,
paired bootstrap confidence intervals and an exact sign test. It does not need
scipy.

Usage:
    python scripts/analyze_pairwise.py --input data/benchmark/eval-dev/judgments.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _percentile(values: List[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))]


def _bootstrap(
    scores_a: List[float],
    scores_b: List[float],
    preferences: List[str],
    *,
    iterations: int = 10000,
    seed: int = 17,
) -> Dict[str, Any]:
    if not scores_a:
        return {}
    rng = random.Random(seed)
    n = len(scores_a)
    mean_diffs = []
    win_rates = []
    for _ in range(iterations):
        indices = [rng.randrange(n) for _ in range(n)]
        diff = sum(scores_a[i] - scores_b[i] for i in indices) / n
        wins = sum(1 for i in indices if preferences[i] == "a")
        losses = sum(1 for i in indices if preferences[i] == "b")
        mean_diffs.append(diff)
        win_rates.append(wins / max(1, wins + losses))
    return {
        "mean_diff_ci95": [round(_percentile(mean_diffs, 0.025), 4), round(_percentile(mean_diffs, 0.975), 4)],
        "win_rate_ci95": [round(_percentile(win_rates, 0.025), 4), round(_percentile(win_rates, 0.975), 4)],
        "iterations": iterations,
    }


def _sign_test(wins: int, losses: int) -> Optional[float]:
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 4)


def analyze(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    scored = [
        row for row in rows
        if row.get("score_a") is not None and row.get("score_b") is not None
    ]
    scores_a = [float(row["score_a"]) for row in scored]
    scores_b = [float(row["score_b"]) for row in scored]
    preferences = [str(row.get("preference") or "").lower() for row in scored]
    wins_a = preferences.count("a")
    wins_b = preferences.count("b")
    ties = preferences.count("tie")
    decisive = wins_a + wins_b
    mean_diff = statistics.mean([a - b for a, b in zip(scores_a, scores_b)]) if scored else 0.0
    result = {
        "items": len(rows),
        "scored": len(scored),
        "wins_a": wins_a,
        "wins_b": wins_b,
        "ties": ties,
        "win_rate_a_decisive": round(wins_a / decisive, 4) if decisive else None,
        "win_rate_a_all": round(wins_a / len(scored), 4) if scored else None,
        "mean_score_a": round(statistics.mean(scores_a), 4) if scores_a else None,
        "mean_score_b": round(statistics.mean(scores_b), 4) if scores_b else None,
        "mean_diff_a_minus_b": round(mean_diff, 4) if scored else None,
        "sign_test_p": _sign_test(wins_a, wins_b),
        "bootstrap": _bootstrap(scores_a, scores_b, preferences),
    }
    by_category: Dict[str, Any] = {}
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in scored:
        groups[str(row.get("category") or "unknown")].append(row)
    for category, group in sorted(groups.items()):
        a = [float(row["score_a"]) for row in group]
        b = [float(row["score_b"]) for row in group]
        prefs = [str(row.get("preference") or "").lower() for row in group]
        by_category[category] = {
            "items": len(group),
            "wins_a": prefs.count("a"),
            "wins_b": prefs.count("b"),
            "ties": prefs.count("tie"),
            "mean_diff": round(statistics.mean([x - y for x, y in zip(a, b)]), 4),
        }
    result["by_category"] = by_category
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = _read_jsonl(args.input)
    result = analyze(rows)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
