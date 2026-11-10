"""Tests for the legacy LLM client factory used by translate.py."""
from __future__ import annotations

from src.core.llm_client import create_llm_client


def test_litellm_client_is_created_with_provider_prefixed_model():
    client = create_llm_client(
        "litellm",
        None,
        "http://localhost:11434",
        "anthropic/claude-haiku-5-5",
    )

    assert client is not None
    assert client.provider_type == "litellm"
    assert client.model == "anthropic/claude-haiku-5-5"
    assert client.provider_kwargs["model"] == "anthropic/claude-haiku-5-5"


def test_unknown_provider_still_returns_none():
    assert create_llm_client("unknown", None, "http://localhost:11434", "model") is None
