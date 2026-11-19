"""The optional spend cap: enforced before each request, recorded in the ledger."""
from __future__ import annotations

import json

import pytest

from src.core.llm.cost_guard import CostGuard
from src.core.llm.exceptions import BillingExhaustedError

# claude-haiku-5.5 is priced at US$ 0.10 in / 0.50 out per 1M tokens in
# src/literary/cost.py, so 1M in + 1M out costs US$ 0.60.
MODEL = "claude-haiku-5-5"


def _guard(tmp_path, cap=0.50, **kwargs):
    return CostGuard(
        cap_usd=cap,
        provider="anthropic",
        model=MODEL,
        book="Test Book",
        stage="translate-rescue",
        ledger_path=tmp_path / "ledger.jsonl",
        **kwargs,
    )


def _rows(tmp_path):
    return [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_record_writes_one_ledger_row_with_the_cap(tmp_path):
    guard = _guard(tmp_path)

    cost = guard.record(1_000_000, 1_000_000)

    assert cost == pytest.approx(0.60)
    (row,) = _rows(tmp_path)
    assert row["provider"] == "anthropic"
    assert row["model"] == MODEL
    assert (row["book"], row["stage"]) == ("Test Book", "translate-rescue")
    assert (row["prompt_tokens"], row["output_tokens"]) == (1_000_000, 1_000_000)
    assert row["cost_usd"] == pytest.approx(0.60)
    assert row["cap_usd"] == 0.50
    assert row["estimated"] is False


def test_check_raises_once_the_cap_is_spent(tmp_path):
    guard = _guard(tmp_path, cap=0.50)
    guard.check()  # nothing spent yet

    guard.record(1_000_000, 0)  # US$ 0.10
    guard.check()  # still under the cap

    guard.record(0, 1_000_000)  # US$ 0.50 more: total 0.60
    with pytest.raises(BillingExhaustedError) as excinfo:
        guard.check()
    assert excinfo.value.provider == "anthropic"
    assert "Test Book" in str(excinfo.value)


def test_a_new_guard_keeps_counting_from_the_ledger(tmp_path):
    first = _guard(tmp_path, cap=0.50)
    first.record(0, 1_000_000)  # US$ 0.50: cap spent

    resumed = _guard(tmp_path, cap=0.50)

    assert resumed.spent_usd == pytest.approx(0.50)
    with pytest.raises(BillingExhaustedError):
        resumed.check()


def test_other_labels_do_not_count_against_the_cap(tmp_path):
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps({"book": "Other", "stage": "translate-rescue", "cost_usd": 9.0}) + "\n"
        + json.dumps({"book": "Test Book", "stage": "auto-audit", "cost_usd": 9.0}) + "\n"
        + "not json\n",
        encoding="utf-8",
    )

    assert _guard(tmp_path).spent_usd == 0.0


def test_unknown_model_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="no price"):
        CostGuard(
            cap_usd=0.50,
            provider="anthropic",
            model="claude-unpriced-9-9",
            ledger_path=tmp_path / "ledger.jsonl",
        )


def test_non_positive_cap_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="greater than zero"):
        _guard(tmp_path, cap=0)


def test_from_env_is_off_when_the_cap_is_unset(monkeypatch):
    monkeypatch.delenv("LLM_MAX_COST_USD", raising=False)

    assert CostGuard.from_env(provider="anthropic", model=MODEL) is None


def test_from_env_reads_cap_labels_and_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MAX_COST_USD", "0.50")
    monkeypatch.setenv("LLM_COST_BOOK", "The Rain Wild Chronicles")
    monkeypatch.setenv("LLM_COST_STAGE", "translate-rescue")
    monkeypatch.setenv("LLM_COST_LEDGER", str(tmp_path / "ledger.jsonl"))

    guard = CostGuard.from_env(provider="anthropic", model=MODEL)

    assert guard.cap_usd == 0.50
    assert (guard.book, guard.stage) == ("The Rain Wild Chronicles", "translate-rescue")
    assert guard.ledger_path == tmp_path / "ledger.jsonl"


def test_from_env_rejects_a_garbage_cap(monkeypatch):
    monkeypatch.setenv("LLM_MAX_COST_USD", "fifty cents")

    with pytest.raises(ValueError, match="must be a number"):
        CostGuard.from_env(provider="anthropic", model=MODEL)
