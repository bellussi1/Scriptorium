"""Compare a cloud run directory against the local Index/Q4 dev run."""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List


def read_rows(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[str(row["id"])] = row
    return rows


def metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("metrics") or {}


def generation(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("generation") or {}


def compare(cloud: Dict[str, Dict[str, Any]], local: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    ids = sorted(set(cloud) & set(local))
    chrf_cloud = [metrics(cloud[i]).get("chrf") for i in ids]
    chrf_local = [metrics(local[i]).get("chrf") for i in ids]
    pairs = [(c, l) for c, l in zip(chrf_cloud, chrf_local) if c is not None and l is not None]
    deltas = [c - l for c, l in pairs]
    by_category: Dict[str, List[float]] = defaultdict(list)
    for item in ids:
        c = metrics(cloud[item]).get("chrf")
        l = metrics(local[item]).get("chrf")
        if c is not None and l is not None:
            by_category[str(cloud[item].get("category") or "unknown")].append(c - l)
    def mean_metric(rows: Dict[str, Dict[str, Any]], key: str):
        values = [
            metrics(rows[i]).get(key)
            for i in ids
            if metrics(rows[i]).get(key) is not None
        ]
        return round(statistics.mean(values), 4) if values else None

    return {
        "rows": len(ids),
        "cloud_chrf": round(statistics.mean(c for c, _ in pairs), 4) if pairs else None,
        "local_chrf": round(statistics.mean(l for _, l in pairs), 4) if pairs else None,
        "delta_cloud_minus_local": round(statistics.mean(deltas), 4) if deltas else None,
        "cloud_wins": sum(1 for d in deltas if d > 1e-9),
        "local_wins": sum(1 for d in deltas if d < -1e-9),
        "ties": sum(1 for d in deltas if abs(d) <= 1e-9),
        "cloud_latency_s": round(
            statistics.mean(generation(cloud[i]).get("latency_s", 0.0) for i in ids), 2
        ) if ids else None,
        "local_latency_s": round(
            statistics.mean(generation(local[i]).get("latency_s", 0.0) for i in ids), 2
        ) if ids else None,
        "cloud_cost_usd": round(sum(generation(cloud[i]).get("cost_usd", 0.0) for i in ids), 6),
        "cloud_name_recall": mean_metric(cloud, "name_recall"),
        "local_name_recall": mean_metric(local, "name_recall"),
        "by_category_delta": {
            category: round(statistics.mean(values), 4)
            for category, values in sorted(by_category.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cloud-run", type=Path, required=True)
    parser.add_argument("--local-run", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=["gemini-3.8-flash", "deepseek-flash", "claude-haiku-5-5"])
    args = parser.parse_args()

    local_index = read_rows(args.local_run / "index-translate-9b.jsonl")
    local_q4 = read_rows(args.local_run / "hy-mt2-7b.jsonl")
    output = {}
    for model in args.models:
        path = args.cloud_run / f"{model}.jsonl"
        if not path.exists():
            continue
        cloud = read_rows(path)
        output[model] = {
            "vs_index": compare(cloud, local_index),
            "vs_q4": compare(cloud, local_q4),
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
