"""Hard spend cap for one paid translation run, recorded in the cost ledger.

Off by default. Setting ``LLM_MAX_COST_USD`` makes a provider that supports it
refuse further requests once the capped label has spent that much: the guard
raises ``BillingExhaustedError``, which aborts the run with the checkpoint
intact (see ``translate.py`` exit code 3). Every paid call appends one row to
``data/cost_ledger.jsonl`` with the cap, so the spend is auditable and a resume
keeps counting from what the same label already spent instead of restarting at
zero.

Environment:
    LLM_MAX_COST_USD   cap in US dollars (required to enable the guard)
    LLM_COST_BOOK      ledger ``book`` label (default: "unlabelled")
    LLM_COST_STAGE     ledger ``stage`` label (default: "translate")
    LLM_COST_LEDGER    ledger path (default: <repo>/data/cost_ledger.jsonl)

The guard fails closed: an invalid cap or a model without a price entry raises
instead of running unguarded.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .exceptions import BillingExhaustedError

ENV_CAP = "LLM_MAX_COST_USD"
ENV_BOOK = "LLM_COST_BOOK"
ENV_STAGE = "LLM_COST_STAGE"
ENV_LEDGER = "LLM_COST_LEDGER"

_DEFAULT_LEDGER = Path(__file__).resolve().parents[3] / "data" / "cost_ledger.jsonl"
_VERSION_DASH = re.compile(r"(\d)-(\d)(?!\d)")


def _price_per_million(provider: str, model: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens from the project's cost registry."""
    from src.literary.cost import get_pricing

    # LiteLLM ids use dashes in versions (claude-haiku-5-5); the registry uses dots.
    candidates = [model, _VERSION_DASH.sub(r"\1.\2", model)]
    for candidate in candidates:
        try:
            pricing = get_pricing(provider, candidate)
        except KeyError:
            continue
        return pricing.input_per_m, pricing.output_per_m
    raise ValueError(
        f"{ENV_CAP} is set but there is no price for {provider}:{model}; "
        "add it to src/literary/cost.py so the cap can be enforced"
    )


class CostGuard:
    """Tracks the spend of one (book, stage) label against a hard cap."""

    def __init__(
        self,
        *,
        cap_usd: float,
        provider: str,
        model: str,
        book: str = "unlabelled",
        stage: str = "translate",
        ledger_path: Optional[Path] = None,
    ):
        if not cap_usd > 0:
            raise ValueError(f"{ENV_CAP} must be greater than zero, got {cap_usd!r}")
        self.cap_usd = float(cap_usd)
        self.provider = provider
        self.model = model
        self.book = book
        self.stage = stage
        self.ledger_path = Path(ledger_path) if ledger_path else _DEFAULT_LEDGER
        self._input_per_m, self._output_per_m = _price_per_million(provider, model)
        self.spent_usd = self._already_spent()

    @classmethod
    def from_env(cls, *, provider: str, model: str) -> Optional["CostGuard"]:
        """Build the guard from the environment, or None when the cap is unset."""
        raw = os.environ.get(ENV_CAP, "").strip()
        if not raw:
            return None
        try:
            cap = float(raw)
        except ValueError as exc:
            raise ValueError(f"{ENV_CAP} must be a number, got {raw!r}") from exc
        ledger = os.environ.get(ENV_LEDGER, "").strip()
        return cls(
            cap_usd=cap,
            provider=provider,
            model=model,
            book=os.environ.get(ENV_BOOK, "").strip() or "unlabelled",
            stage=os.environ.get(ENV_STAGE, "").strip() or "translate",
            ledger_path=Path(ledger) if ledger else None,
        )

    def _already_spent(self) -> float:
        """Spend the ledger already holds for this label (a resume keeps the cap)."""
        if not self.ledger_path.exists():
            return 0.0
        total = 0.0
        with self.ledger_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("book") == self.book and row.get("stage") == self.stage:
                    total += float(row.get("cost_usd") or 0)
        return total

    def check(self) -> None:
        """Raise before a request when the cap is already spent."""
        if self.spent_usd >= self.cap_usd:
            raise BillingExhaustedError(
                f"Cost cap reached for {self.book} / {self.stage}: "
                f"US$ {self.spent_usd:.4f} spent of US$ {self.cap_usd:.2f}",
                provider=self.provider,
            )

    def cost_of(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self._input_per_m + completion_tokens * self._output_per_m
        ) / 1_000_000

    def record(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Add one paid call to the running total and to the ledger."""
        cost = self.cost_of(prompt_tokens, completion_tokens)
        self.spent_usd += cost
        row = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "provider": self.provider,
            "model": self.model,
            "book": self.book,
            "stage": self.stage,
            "prompt_tokens": int(prompt_tokens),
            "output_tokens": int(completion_tokens),
            "cost_usd": round(cost, 6),
            "cap_usd": self.cap_usd,
            "estimated": False,
        }
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:
            # The in-memory total still enforces the cap; a retry would pay twice.
            print(f"[cost-guard] could not write {self.ledger_path}: {exc}")
        return cost
