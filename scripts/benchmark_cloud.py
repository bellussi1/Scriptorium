"""Benchmark the cheap cloud providers on the same literary corpus.

Runs inside the app container so it can reuse the provider factory and the
native credentials from `.env`. The prompt is the controlled literary prompt
(system + glossary + style), not each provider's chat-tuned template; the goal
is a like-for-like translation comparison with the local models.

Usage:
    docker compose -f docker-compose.dev.yml exec -T -e TEMPERATURE=0 app \
      python scripts/benchmark_cloud.py \
      --models gemini-3.8-flash deepseek-flash claude-haiku-5-5 \
      --corpus data/benchmark/literary/eval_farseer_dev.jsonl \
      --out-root data/benchmark/cloud-dev
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.literary.adapters import LITERARY_SYSTEM  # noqa: E402
from benchmark.literary.corpus import load_corpus  # noqa: E402
from benchmark.literary.metrics import score_output  # noqa: E402
from scripts.benchmark_fase_d import _resources  # noqa: E402
from src.core.llm.factory import create_llm_provider  # noqa: E402
from src.literary.cost import get_pricing  # noqa: E402

MODELS: Dict[str, Dict[str, str]] = {
    "gemini-3.8-flash": {
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "label": "Gemini 3.8 Flash",
        "pricing_provider": "gemini",
        "pricing_model": "gemini-3.8-flash",
    },
    "deepseek-flash": {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "label": "DeepSeek V4.1 Flash",
        "pricing_provider": "deepseek",
        "pricing_model": "deepseek-flash",
    },
    "claude-haiku-5-5": {
        "provider": "litellm",
        "model": "anthropic/claude-haiku-5-5",
        "label": "Claude Haiku 5.5",
        "pricing_provider": "anthropic",
        "pricing_model": "claude-haiku-5.5",
    },
}


def _glossary_text(glossary: Dict[str, str]) -> str:
    return "\n".join(f"- {source} -> {target}" for source, target in glossary.items())


def build_system_prompt(style: str, glossary: Dict[str, str]) -> str:
    system = LITERARY_SYSTEM
    if style:
        system += "\n" + style.strip()
    if glossary:
        system += "\n\nTerminology (mandatory):\n" + _glossary_text(glossary)
    return system


def _run_dir(root: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(root) / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    successful = [row for row in rows if not row["generation"].get("error")]

    def mean_metric(key: str):
        values = [
            row["metrics"].get(key)
            for row in successful
            if row["metrics"].get(key) is not None
        ]
        return round(statistics.mean(values), 4) if values else None

    chrf = [row["metrics"]["chrf"] for row in successful if row["metrics"].get("chrf") is not None]
    latency = [row["generation"]["latency_s"] for row in successful]
    prompt_tokens = sum(row["generation"].get("prompt_tokens", 0) for row in successful)
    output_tokens = sum(row["generation"].get("output_tokens", 0) for row in successful)
    cost = sum(row["generation"].get("cost_usd", 0.0) for row in successful)
    return {
        "rows": len(rows),
        "errors": len(rows) - len(successful),
        "chrf_mean": round(statistics.mean(chrf), 4) if chrf else None,
        "chrf_std": round(statistics.stdev(chrf), 4) if len(chrf) > 1 else None,
        "name_recall_mean": mean_metric("name_recall"),
        "length_ratio_mean": mean_metric("length_ratio"),
        "english_leakage_mean": mean_metric("english_leakage"),
        "repetition_mean": mean_metric("repetition_ratio"),
        "latency_mean_s": round(statistics.mean(latency), 2) if latency else None,
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 6),
    }


async def run(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus)
    if args.limit:
        corpus = corpus[:args.limit]
    glossary, style = _resources(
        args.resource_author,
        args.resource_universe,
        args.resource_subseries,
        args.resource_book,
        args.resource_book_order,
    )
    system_prompt = build_system_prompt(style, glossary)
    out_dir = _run_dir(args.out_root)
    summary: Dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": str(Path(args.corpus).resolve()),
        "models": args.models,
        "excerpts": len(corpus),
        "run_dir": str(out_dir),
        "results": [],
    }

    for key in args.models:
        if key not in MODELS:
            raise SystemExit(f"unknown cloud model: {key}")
        spec = MODELS[key]
        pricing = get_pricing(spec["pricing_provider"], spec["pricing_model"])
        provider = create_llm_provider(spec["provider"], model=spec["model"])
        semaphore = asyncio.Semaphore(max(1, args.concurrency))

        async def process(index: int, excerpt: Any) -> tuple[int, Dict[str, Any]]:
            async with semaphore:
                started = time.time()
                error = ""
                content = ""
                response = None
                try:
                    response = await provider.generate(
                        excerpt.text,
                        system_prompt=system_prompt,
                        timeout=args.timeout,
                    )
                    content = (response.content or "").strip() if response else ""
                    if not content:
                        error = "empty response"
                except Exception as exc:
                    error = str(exc)
                latency = round(time.time() - started, 3)
                prompt_tokens = int(getattr(response, "prompt_tokens", 0) or 0)
                output_tokens = int(getattr(response, "completion_tokens", 0) or 0)
                cost = (
                    prompt_tokens * pricing.input_price() / 1_000_000
                    + output_tokens * pricing.output_price() / 1_000_000
                )
                metrics = score_output(
                    excerpt.text,
                    content,
                    reference=excerpt.reference_pt,
                    glossary=glossary,
                )
                row = {
                    "_index": index,
                    "id": excerpt.id,
                    "book": excerpt.book,
                    "author": excerpt.author,
                    "category": excerpt.category,
                    "model": key,
                    "model_label": spec["label"],
                    "provider": spec["provider"],
                    "provider_model": spec["model"],
                    "generation": {
                        "text": content,
                        "latency_s": latency,
                        "prompt_tokens": prompt_tokens,
                        "output_tokens": output_tokens,
                        "cost_usd": round(cost, 8),
                        "error": error,
                        "finish_reason": getattr(response, "finish_reason", None) if response else None,
                    },
                    "metrics": metrics,
                    "source_chars": len(excerpt.text),
                }
                return index, row

        tasks = [
            asyncio.create_task(process(index, excerpt))
            for index, excerpt in enumerate(corpus, 1)
        ]
        rows: List[Dict[str, Any]] = []
        for completed in asyncio.as_completed(tasks):
            index, row = await completed
            rows.append(row)
            print(
                f"{key} {index:02d}/{len(corpus)} {row['category']:14s} "
                f"chrF={row['metrics'].get('chrf'):.4f} "
                f"lat={row['generation']['latency_s']:.1f}s "
                f"cost=${row['generation']['cost_usd']:.5f} "
                f"err={bool(row['generation']['error'])}",
                flush=True,
            )
        rows.sort(key=lambda item: item["_index"])
        for row in rows:
            row.pop("_index", None)
        summary["results"].extend(rows)
        with (out_dir / f"{key}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        summary.setdefault("summary", {})[key] = _summary(rows)

    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary.get("summary", {}), ensure_ascii=False, indent=2))
    print("wrote", out_dir)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--models", nargs="+", default=list(MODELS))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out-root", default="data/benchmark/cloud")
    parser.add_argument("--resource-author", default="robin-hobb")
    parser.add_argument("--resource-universe", default="realm-of-the-elderlings")
    parser.add_argument("--resource-subseries", default="farseer")
    parser.add_argument("--resource-book", default="assassins-apprentice")
    parser.add_argument("--resource-book-order", type=float, default=3)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
