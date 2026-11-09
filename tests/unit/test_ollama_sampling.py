"""Ollama sampling is explicit and the strict placeholder contract is on."""
from __future__ import annotations

from src.config import (
    OLLAMA_REPEAT_PENALTY,
    OLLAMA_TEMPERATURE,
    OLLAMA_TOP_K,
    OLLAMA_TOP_P,
)
from src.core.llm.providers.ollama import OllamaProvider
from src.prompts.prompts import generate_translation_prompt


def test_ollama_sampling_is_opt_in(monkeypatch):
    provider = OllamaProvider(model="stub", context_window=8192)
    assert provider._sampling_options() == {}

    monkeypatch.setattr(
        "src.core.llm.providers.ollama.OLLAMA_SAMPLING_ENABLED", True
    )
    assert provider._sampling_options() == {
        "temperature": OLLAMA_TEMPERATURE,
        "top_p": OLLAMA_TOP_P,
        "top_k": OLLAMA_TOP_K,
        "repeat_penalty": OLLAMA_REPEAT_PENALTY,
    }


def _translate(**overrides):
    values = {
        "main_content": "hello [id0]",
        "context_before": "",
        "context_after": "",
        "previous_translation_context": "",
        "source_language": "English",
        "target_language": "Portuguese (Brazil)",
        "has_placeholders": True,
        "placeholder_format": ("[id", "]"),
    }
    values.update(overrides)
    return generate_translation_prompt(**values)


def test_strict_placeholder_contract_is_in_the_default_prompt():
    pair = _translate()
    assert "PLACEHOLDER INTEGRITY (NON-NEGOTIABLE)" in pair.system
    assert "[idN]" in pair.system


def test_strict_placeholder_contract_can_be_disabled():
    pair = _translate(prompt_options={"strict_placeholder_prompt": False})
    assert "PLACEHOLDER INTEGRITY (NON-NEGOTIABLE)" not in pair.system


def test_plain_text_mode_does_not_get_the_placeholder_contract():
    pair = _translate(has_placeholders=False)
    assert "PLACEHOLDER INTEGRITY (NON-NEGOTIABLE)" not in pair.system
