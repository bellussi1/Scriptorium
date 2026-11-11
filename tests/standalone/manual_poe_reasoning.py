"""
Live check that Poe bots stop reasoning and searching when Scriptorium asks them to.

Runs one real translation per bot family through the project's factory and
prints the resolved overrides plus the token counts, then repeats the first bot
with the bot's own defaults so the difference is visible in the same output.
This is the test that proves the feature works against the live API, beyond the
schema mapping pinned by tests/unit/test_poe_reasoning.py.

Requires POE_API_KEY in .env. Costs a handful of Poe points (one short prompt
per bot).

Run from repo root:
    python tests/standalone/manual_poe_reasoning.py

Pass bot names to check others:
    python tests/standalone/manual_poe_reasoning.py kimi-k3 qwen3-max-thinking-el
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.console import ensure_utf8_stdio

ensure_utf8_stdio()

from src.core.llm.factory import create_llm_provider

# One bot per knob: thinking_level (+ web_search on by default), thinking_budget,
# reasoning_effort (+ web_search on), enable_thinking, and a bot with no knob.
DEFAULT_MODELS = [
    "gemini-3.6-flash",
    "claude-haiku-4.5",
    "grok-4.5",
    "glm-5.2",
    "gpt-4o",
]

SYSTEM_PROMPT = "You are a professional literary translator. Output only the translation."
USER_PROMPT = (
    "Translate the following English text into French. "
    "Return only the translation, wrapped in <TRANSLATED></TRANSLATED>.\n\n"
    "<TRANSLATE>The old lighthouse keeper climbed the spiral stairs at dusk, "
    "counting each step as he had for forty years. The lamp needed lighting "
    "before the fishing boats turned home.</TRANSLATE>"
)


async def run_one(model: str, override_defaults: bool) -> None:
    provider = create_llm_provider(
        "poe",
        model=model,
        poe_disable_thinking=override_defaults,
        poe_disable_web_search=override_defaults,
    )
    try:
        overrides = await provider._get_bot_overrides()
        response = await provider.generate(USER_PROMPT, system_prompt=SYSTEM_PROMPT)
        if response is None:
            print(f"  {model:24s} FAILED (no response)")
            return
        print(f"  {model:24s} overrides={overrides or '{}'}")
        print(f"  {'':24s} prompt={response.prompt_tokens} "
              f"completion={response.completion_tokens} "
              f"chars={len(response.content)}")
        print(f"  {'':24s} {response.content.strip()[:120]}")
    finally:
        await provider.close()


async def main() -> None:
    models = sys.argv[1:] or DEFAULT_MODELS

    print("Reasoning and web search minimised (Scriptorium defaults):")
    for model in models:
        await run_one(model, True)

    print(f"\nSame prompt on {models[0]} with the bot's own defaults:")
    await run_one(models[0], False)

    print("\nExpect fewer completion tokens in the first block for any bot that "
          "advertises a reasoning knob, and fewer prompt tokens for any bot that "
          "searches the web by default.")


asyncio.run(main())
