"""Cost model calibrated on the user's books, not on generic assumptions.

Prices are USD per one million tokens. The registry records the source and the
date each price was checked, so a stale estimate is visible instead of silent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import CostEstimate

PRICE_CHECKED_AT = "2026-11-07"

# Measured on the user's EPUBs with cl100k_base (see docs/project/COST_MODEL.md).
# English literary prose: 1.21-1.37 tokens/word. Portuguese output: 1.64-1.83
# tokens/word. The word count shrinks ~3% in PT, but the token count grows
# ~1.36x because Portuguese tokenizes worse. Do not use a word ratio here.
DEFAULT_TOKENS_PER_WORD = 1.30
DEFAULT_OUTPUT_TOKEN_RATIO = 1.36
DEFAULT_OUTPUT_RATIO = DEFAULT_OUTPUT_TOKEN_RATIO  # backward-compatible alias


@dataclass
class Pricing:
    provider: str
    model: str
    input_per_m: float
    output_per_m: float
    cache_read_per_m: float = 0.0
    cache_write_per_m: float = 0.0
    batch_multiplier: float = 1.0
    peak_multiplier: float = 1.0
    offpeak_multiplier: float = 1.0
    context_window: int = 0
    data_policy: str = ""
    source: str = ""
    notes: str = ""

    def input_price(self, *, batch: bool = False, offpeak: bool = False) -> float:
        price = self.input_per_m
        if batch:
            price *= self.batch_multiplier
        if offpeak:
            price *= self.offpeak_multiplier
        return price

    def output_price(self, *, batch: bool = False, offpeak: bool = False) -> float:
        price = self.output_per_m
        if batch:
            price *= self.batch_multiplier
        if offpeak:
            price *= self.offpeak_multiplier
        return price


PRICING: Dict[str, Pricing] = {
    # Local models: no API cost. Electricity is not included.
    "ollama:translategemma-12b": Pricing("ollama", "translategemma-12b", 0, 0, context_window=2048, notes="~2K-token regime; 8.1 GB Q4_K_M"),
    "ollama:hy-mt2-7b": Pricing("ollama", "hy-mt2-7b", 0, 0, context_window=8192, notes="practical context ~8K; Q4_K_M ~4.4 GB"),
    "ollama:index-translate-9b": Pricing("ollama", "index-translate-9b", 0, 0, context_window=32768, notes="Q4_K_M ~5.78 GB"),
    "ollama:qwen3-14b": Pricing("ollama", "qwen3:14b", 0, 0, context_window=32768, notes="9.3 GB Q4; hybrid GPU/CPU on 8 GB VRAM"),
    "ollama:qwen3.5-4b": Pricing("ollama", "qwen3.5:4b", 0, 0, context_window=32768, notes="3.4 GB; pipeline smoke tests"),

    # DeepSeek official API (api.deepseek.com).
    "deepseek:deepseek-flash": Pricing(
        "deepseek", "deepseek-flash", 0.30, 1.20, 0.006, 0.0,
        batch_multiplier=1.0, peak_multiplier=1.0, offpeak_multiplier=0.5,
        context_window=1_000_000,
        data_policy="May train on API data by default; no published ZDR tier. Do not send copyrighted books without informed consent.",
        source="https://api-docs.deepseek.com/quick_start/pricing",
        notes="V4.1 Flash 1017. Peak $0.30/$1.20; off-peak $0.15/$0.60. Cache hit $0.006 peak / $0.003 off-peak.",
    ),
    "deepseek:deepseek-v4-pro": Pricing(
        "deepseek", "deepseek-v4-pro", 1.32, 3.96, 0.044, 0.0,
        peak_multiplier=1.0, offpeak_multiplier=0.5, context_window=1_000_000,
        data_policy="Same DeepSeek policy as deepseek-flash.",
        source="https://api-docs.deepseek.com/quick_start/pricing",
        notes="Being routed to V4.1 Flash in some periods; verify before use. Peak $1.32/$3.96; off-peak $0.66/$1.98.",
    ),

    # Google Gemini official API.
    "gemini:gemini-3.8-flash": Pricing(
        "gemini", "gemini-3.8-flash", 0.75, 3.75, 0.075, 0.0,
        batch_multiplier=0.5, context_window=1_048_576,
        data_policy="Paid tier: content not used to improve products; logs retained up to 55 days by default (configurable 7/14/28/55).",
        source="https://ai.google.dev/gemini-api/docs/pricing",
        notes="Promo through 2026-12-31; doubles on 2027-01-01.",
    ),
    "gemini:gemini-3.5-flash-lite": Pricing(
        "gemini", "gemini-3.5-flash-lite", 0.30, 2.50, 0.03, 0.0,
        batch_multiplier=0.5, context_window=1_048_576,
        data_policy="Paid tier: content not used to improve products.",
        source="https://ai.google.dev/gemini-api/docs/pricing",
    ),
    "gemini:gemini-2.5-flash-lite": Pricing(
        "gemini", "gemini-2.5-flash-lite", 0.10, 0.40, 0.01, 0.0,
        batch_multiplier=0.5, context_window=1_048_576,
        data_policy="Paid tier: content not used to improve products.",
        source="https://ai.google.dev/gemini-api/docs/pricing",
        notes="Deprecated; routes to newer models. Use only for comparison.",
    ),
    "gemini:gemini-3-flash-preview": Pricing(
        "gemini", "gemini-3-flash-preview", 0.50, 3.00, 0.05, 0.0,
        batch_multiplier=0.5, context_window=1_048_576,
        data_policy="Paid tier: content not used to improve products.",
        source="https://ai.google.dev/gemini-api/docs/pricing",
        notes="Preview; verify availability.",
    ),

    # OpenAI official API.
    "openai:gpt-6-luna": Pricing(
        "openai", "gpt-6-luna", 0.10, 0.50, 0.01, 0.125,
        batch_multiplier=0.5, context_window=1_050_000,
        data_policy="API data not used for training by default; 30-day abuse logs; ZDR for eligible customers.",
        source="https://platform.openai.com/docs/pricing",
    ),
    "openai:gpt-5.4-nano": Pricing(
        "openai", "gpt-5.4-nano", 0.20, 1.25, 0.02, 0.0,
        batch_multiplier=0.5, context_window=1_050_000,
        data_policy="API data not used for training by default; 30-day abuse logs.",
        source="https://platform.openai.com/docs/pricing",
    ),
    "openai:gpt-5.4-mini": Pricing(
        "openai", "gpt-5.4-mini", 0.75, 4.50, 0.075, 0.0,
        batch_multiplier=0.5, context_window=1_050_000,
        data_policy="API data not used for training by default; 30-day abuse logs.",
        source="https://platform.openai.com/docs/pricing",
    ),
    "openai:gpt-6.1-terra": Pricing(
        "openai", "gpt-6.1-terra", 1.00, 5.00, 0.05, 1.25,
        batch_multiplier=0.5, context_window=1_050_000,
        data_policy="API data not used for training by default; 30-day abuse logs.",
        source="https://platform.openai.com/docs/pricing",
    ),

    # Anthropic and OpenRouter shortlist (OpenRouter prices include its fee).
    "anthropic:claude-haiku-5.5": Pricing(
        "anthropic", "claude-haiku-5.5", 0.10, 0.50, 0.01, 0.125,
        batch_multiplier=0.5, context_window=1_000_000,
        data_policy="Commercial API: inputs/outputs not used for training by default.",
        source="https://www.anthropic.com/pricing",
    ),
    "openrouter:google/gemini-3.8-flash": Pricing(
        "openrouter", "google/gemini-3.8-flash", 0.825, 4.125, 0.0825, 0.0,
        batch_multiplier=0.5, context_window=1_048_576,
        data_policy="Provider-dependent; enforce ZDR + data_collection=deny for private books.",
        source="https://openrouter.ai/api/v1/models",
    ),
    "openrouter:deepseek/deepseek-v4.1-flash-1017": Pricing(
        "openrouter", "deepseek/deepseek-v4.1-flash-1017", 0.15, 0.60, 0.003, 0.0,
        context_window=1_048_576,
        data_policy="Provider-dependent; DeepSeek provider may train. Enforce ZDR or avoid.",
        source="https://openrouter.ai/api/v1/models",
    ),
    "openrouter:openai/gpt-6-luna": Pricing(
        "openrouter", "openai/gpt-6-luna", 0.10, 0.50, 0.01, 0.0,
        batch_multiplier=0.5, context_window=1_050_000,
        data_policy="Provider-dependent; enforce ZDR for private books.",
        source="https://openrouter.ai/api/v1/models",
    ),
    "openrouter:anthropic/claude-haiku-5.5": Pricing(
        "openrouter", "anthropic/claude-haiku-5.5", 0.10, 0.50, 0.01, 0.0,
        batch_multiplier=0.5, context_window=1_000_000,
        data_policy="Provider-dependent; enforce ZDR for private books.",
        source="https://openrouter.ai/api/v1/models",
    ),
    "openrouter:z-ai/glm-5.3": Pricing(
        "openrouter", "z-ai/glm-5.3", 0.0699, 1.40, 0.0689, 0.0,
        context_window=1_048_576,
        data_policy="Provider-dependent; verify before use.",
        source="https://openrouter.ai/api/v1/models",
    ),
    "openrouter:minimax/minimax-m3.1-flash": Pricing(
        "openrouter", "minimax/minimax-m3.1-flash", 0.075, 0.30, 0.0075, 0.0,
        context_window=1_048_576,
        data_policy="Provider-dependent; verify before use.",
        source="https://openrouter.ai/api/v1/models",
    ),
}

ALIASES = {
    "deepseek-v4.1-flash": "deepseek:deepseek-flash",
    "deepseek-flash": "deepseek:deepseek-flash",
    "deepseek-v4-flash": "deepseek:deepseek-flash",
    "gemini-3.8-flash": "gemini:gemini-3.8-flash",
    "gemini-3.5-flash-lite": "gemini:gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite": "gemini:gemini-2.5-flash-lite",
    "gemini-3-flash-preview": "gemini:gemini-3-flash-preview",
    "gpt-6-luna": "openai:gpt-6-luna",
    "gpt-5.4-nano": "openai:gpt-5.4-nano",
    "gpt-5.4-mini": "openai:gpt-5.4-mini",
    "gpt-6.1-terra": "openai:gpt-6.1-terra",
    "claude-haiku-5.5": "anthropic:claude-haiku-5.5",
    "translategemma-12b": "ollama:translategemma-12b",
    "hy-mt2-7b": "ollama:hy-mt2-7b",
    "index-translate-9b": "ollama:index-translate-9b",
    "qwen3-14b": "ollama:qwen3-14b",
    "qwen3.5-4b": "ollama:qwen3.5-4b",
}


def get_pricing(provider: str, model: str) -> Pricing:
    key = f"{provider}:{model}"
    if key in PRICING:
        return PRICING[key]
    if key in ALIASES:
        return PRICING[ALIASES[key]]
    if model in ALIASES:
        return PRICING[ALIASES[model]]
    # Last resort: match by model name alone.
    for pricing in PRICING.values():
        if pricing.model == model:
            return pricing
    raise KeyError(f"No pricing entry for {provider}:{model}. Add it to src/literary/cost.py.")


def estimate_book(
    *,
    word_count: int,
    provider: str,
    model: str,
    tokens_per_word: float = DEFAULT_TOKENS_PER_WORD,
    output_ratio: float = DEFAULT_OUTPUT_RATIO,
    max_tokens_per_chunk: int = 450,
    chunk_fill_ratio: float = 0.78,
    system_prompt_tokens: int = 500,
    user_template_tokens: int = 60,
    glossary_tokens_per_chunk: int = 0,
    style_tokens: int = 0,
    context_tokens_per_chunk: int = 50,
    passes: int = 1,
    refine_input_factor: float = 1.85,
    refine_output_factor: float = 0.97,
    retry_rate: float = 0.10,
    cache_hit_fraction: float = 0.75,
    batch: bool = False,
    offpeak: bool = False,
    judge: bool = False,
    judge_input_tokens: int = 350,
    judge_output_tokens: int = 120,
) -> CostEstimate:
    """Estimate one book.

    ``output_ratio`` is a token ratio, not a word ratio. Measured EN->PT-BR
    output is ~1.36x the English input token count even though the Portuguese
    word count is ~3% lower.

    ``refine_input_factor`` is the extra input of a source-aware refinement
    pass: draft + source + prompt, roughly 1.85x a translation chunk. A
    monolingual refinement would be cheaper but cannot repair accuracy, so the
    model deliberately prices the source-aware design.
    """
    pricing = get_pricing(provider, model)
    source_tokens = max(0, int(round(word_count * tokens_per_word)))
    chunk_size = max(100, int(max_tokens_per_chunk * chunk_fill_ratio))
    chunks = max(1, math.ceil(source_tokens / chunk_size)) if source_tokens else 0
    if chunks == 0:
        return CostEstimate(model=model, provider=provider, source_words=word_count, input_tokens=0, output_tokens=0, input_cost=0, output_cost=0, total_cost=0, assumptions={})

    base_input = chunk_size + system_prompt_tokens + user_template_tokens + glossary_tokens_per_chunk + style_tokens + context_tokens_per_chunk
    base_output = chunk_size * output_ratio
    input_tokens = 0.0
    output_tokens = 0.0
    input_cost = 0.0
    output_cost = 0.0

    in_price = pricing.input_price(batch=batch, offpeak=offpeak)
    out_price = pricing.output_price(batch=batch, offpeak=offpeak)
    cache_price = pricing.cache_read_per_m * (pricing.batch_multiplier if batch else 1.0) * (pricing.offpeak_multiplier if offpeak else 1.0)

    for pass_index in range(passes):
        if pass_index == 0:
            pass_input = base_input
            pass_output = base_output
        else:
            pass_input = base_input * refine_input_factor
            pass_output = base_output * refine_output_factor
        input_tokens += chunks * pass_input * (1 + retry_rate)
        output_tokens += chunks * pass_output * (1 + retry_rate)
        # Only the stable prefix is assumed cacheable; the chunk itself is not.
        cacheable = min(system_prompt_tokens + style_tokens, pass_input) * cache_hit_fraction
        input_cost += chunks * (pass_input - cacheable) / 1_000_000 * in_price * (1 + retry_rate)
        input_cost += chunks * cacheable / 1_000_000 * (cache_price or in_price) * (1 + retry_rate)
        output_cost += chunks * pass_output / 1_000_000 * out_price * (1 + retry_rate)

    if judge:
        judge_input = chunks * judge_input_tokens
        judge_output = chunks * judge_output_tokens
        input_tokens += judge_input
        output_tokens += judge_output
        input_cost += judge_input / 1_000_000 * pricing.input_price(batch=batch, offpeak=offpeak)
        output_cost += judge_output / 1_000_000 * pricing.output_price(batch=batch, offpeak=offpeak)

    total = input_cost + output_cost
    return CostEstimate(
        model=model,
        provider=provider,
        source_words=word_count,
        input_tokens=int(round(input_tokens)),
        output_tokens=int(round(output_tokens)),
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total,
        passes=passes,
        retry_rate=retry_rate,
        assumptions={
            "tokens_per_word": tokens_per_word,
            "output_ratio": output_ratio,
            "chunks": chunks,
            "chunk_tokens": chunk_size,
            "max_tokens_per_chunk": max_tokens_per_chunk,
            "system_prompt_tokens": system_prompt_tokens,
            "glossary_tokens_per_chunk": glossary_tokens_per_chunk,
            "style_tokens": style_tokens,
            "context_tokens_per_chunk": context_tokens_per_chunk,
            "cache_hit_fraction": cache_hit_fraction,
            "batch": batch,
            "offpeak": offpeak,
            "judge": judge,
            "pricing_source": pricing.source,
            "price_checked_at": PRICE_CHECKED_AT,
            "data_policy": pricing.data_policy,
            "notes": pricing.notes,
        },
    )


SCENARIOS = {
    "A": {
        "label": "cheap single pass",
        "provider": "deepseek",
        "model": "deepseek-flash",
        "passes": 1,
        "refine": False,
    },
    "B": {
        "label": "cheap + source-aware refinement",
        "provider": "deepseek",
        "model": "deepseek-flash",
        "passes": 2,
        "refine": True,
    },
    "C": {
        "label": "strong single pass",
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "passes": 1,
        "refine": False,
    },
    "D": {
        "label": "local translation + selective cloud review (10%)",
        "provider": "ollama",
        "model": "hy-mt2-7b",
        "passes": 1,
        "refine": False,
        "cloud_review_fraction": 0.10,
        "review_provider": "gemini",
        "review_model": "gemini-3.8-flash",
    },
    "E": {
        "label": "all local",
        "provider": "ollama",
        "model": "hy-mt2-7b",
        "passes": 1,
        "refine": False,
    },
}


def estimate_scenario(book_words: int, scenario: str, **overrides: Any) -> Dict[str, Any]:
    config = dict(SCENARIOS[scenario])
    config.update(overrides)
    label = config.pop("label")
    review_fraction = float(config.pop("cloud_review_fraction", 0.0))
    review_provider = config.pop("review_provider", "")
    review_model = config.pop("review_model", "")
    provider = config.pop("provider")
    model = config.pop("model")
    passes = int(config.pop("passes", 1))
    config.pop("refine", None)
    estimate = estimate_book(
        word_count=book_words,
        provider=provider,
        model=model,
        passes=passes,
        **config,
    )
    payload = estimate.to_dict()
    payload["scenario"] = scenario
    payload["label"] = label
    if review_fraction and review_provider and review_model:
        review = estimate_book(
            word_count=int(book_words * review_fraction),
            provider=review_provider,
            model=review_model,
            passes=2,
            **config,
        )
        payload["selective_review"] = review.to_dict()
        payload["total_cost"] = round(payload["total_cost"] + review.total_cost, 4)
    return payload


def estimate_series(books: List[Dict[str, Any]], scenarios: Optional[List[str]] = None) -> Dict[str, Any]:
    scenarios = scenarios or list(SCENARIOS.keys())
    results: Dict[str, Any] = {"books": [], "totals": {scenario: 0.0 for scenario in scenarios}}
    for book in books:
        words = int(book.get("word_count") or 0)
        if words <= 0:
            continue
        row = {"title": book.get("title", ""), "calibre_id": book.get("calibre_id"), "words": words}
        for scenario in scenarios:
            estimate = estimate_scenario(words, scenario)
            row[scenario] = estimate
            results["totals"][scenario] += estimate.get("total_cost", 0.0)
        results["books"].append(row)
    results["totals"] = {key: round(value, 4) for key, value in results["totals"].items()}
    return results
