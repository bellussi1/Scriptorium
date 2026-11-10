"""Show local cloud spend against the budgets in data/budgets.json.

Reads data/cost_ledger.jsonl, sums cost_usd by provider and model, and compares
to the snapshot limits. This is a local report, not a provider balance query.

Usage:
    python scripts/lit_cost.py
    python scripts/lit_cost.py --json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = ROOT / "data" / "budgets.json"
LEDGER = ROOT / "data" / "cost_ledger.jsonl"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _read_ledger(path: Path) -> list[Dict[str, Any]]:
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    budgets = _read_json(BUDGETS)
    rows = _read_ledger(LEDGER)
    by_provider: Dict[str, float] = defaultdict(float)
    by_model: Dict[str, float] = defaultdict(float)
    estimated: Dict[str, float] = defaultdict(float)
    for row in rows:
        provider = str(row.get("provider") or "unknown")
        model = str(row.get("model") or "unknown")
        cost = float(row.get("cost_usd") or 0.0)
        by_provider[provider] += cost
        by_model[model] += cost
        if row.get("estimated"):
            estimated[provider] += cost

    report = {
        "ledger": str(LEDGER),
        "budgets": budgets,
        "spent_by_provider": dict(sorted(by_provider.items())),
        "spent_by_model": dict(sorted(by_model.items())),
        "estimated_by_provider": dict(sorted(estimated.items())),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"ledger: {LEDGER}")
    for provider, raw in sorted(budgets.items()):
        budget = raw if isinstance(raw, dict) else {}
        currency = str(budget.get("currency") or "USD")
        snapshot = str(budget.get("snapshot") or "unknown date")
        note = str(budget.get("note") or "")
        spent = by_provider.get(provider, 0.0)
        cap = float(budget.get("cap") or 0.0)
        cap_usd = float(budget.get("cap_usd") or 0.0)
        balance = float(budget.get("balance") or 0.0)
        if currency == "BRL":
            print(
                f"{provider:12s} cap R$ {cap:7.2f} (~US$ {cap_usd:6.2f}); "
                f"ledger total US$ {spent:6.2f} historical  {note}"
            )
        else:
            print(
                f"{provider:12s} available US$ {balance:6.2f} (snapshot {snapshot}); "
                f"ledger total US$ {spent:6.2f} historical  {note}"
            )
    unknown = sorted(set(by_provider) - set(budgets))
    for provider in unknown:
        print(f"{provider:12s} US$ {by_provider[provider]:7.2f}  (no budget entry)")
    print("\nby model:")
    for model, cost in sorted(by_model.items(), key=lambda item: -item[1]):
        print(f"  {model:40s} US$ {cost:7.4f}")
    if estimated:
        print("\nestimated rows (not provider invoices):")
        for provider, cost in sorted(estimated.items()):
            print(f"  {provider:12s} US$ {cost:7.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
