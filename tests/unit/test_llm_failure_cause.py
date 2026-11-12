"""A request that returns no response must say why, both on the provider and in the translator log.

No network: the Ollama provider talks to an httpx.MockTransport, and the
translator tests use a fake client.
"""
import asyncio

import httpx

from src.core import translator as translator_module
from src.core.llm.base import LLMResponse
from src.core.llm.failure import LLMFailure
from src.core.llm.providers import ollama as ollama_module
from src.core.llm.providers.ollama import OllamaProvider
from src.core.llm_client import LLMClient


def test_describe_names_the_exception_status_and_message():
    failure = LLMFailure.from_exception(
        "ollama", "http", ValueError("boom"), message="model not loaded", status=500)

    assert failure.describe() == "ollama ValueError (HTTP 500): model not loaded"


def test_describe_without_status_or_message():
    failure = LLMFailure.from_exception("ollama", "timeout", TimeoutError(""))

    assert failure.describe() == "ollama TimeoutError"


def test_message_is_truncated_for_the_log():
    failure = LLMFailure.from_exception("ollama", "unexpected", RuntimeError("x" * 1000))

    assert len(failure.message) == 300


class _FakeProvider:
    """Provider stand-in that fails the way a provider does: returns None and records why."""

    def __init__(self, failure=None, response=None):
        self.last_failure = None
        self._failure = failure
        self._response = response

    async def generate(self, prompt, system_prompt=None):
        self.last_failure = self._failure
        return self._response

    def extract_translation(self, response):
        return None


def test_client_exposes_the_last_failure_and_resets_it_per_call():
    client = LLMClient(provider_type="ollama")
    failure = LLMFailure.from_exception("ollama", "http", RuntimeError("x"), status=503)
    fake = _FakeProvider(failure=failure)
    client._provider = fake

    assert client.last_failure is None
    asyncio.run(client.generate("hi"))
    assert client.last_failure is failure

    fake._failure = None
    asyncio.run(client.generate("hi"))
    assert client.last_failure is None


def _translate(client, has_placeholders=False):
    logged = []

    def capture(event, message, data=None):
        logged.append((event, message))

    result = asyncio.run(translator_module.generate_translation_request(
        "Hello world, this chunk has enough text to translate.",
        context_before="",
        context_after="",
        previous_translation_context="",
        source_language="English",
        target_language="Portuguese (Brazil)",
        model="index-9b",
        llm_client=client,
        log_callback=capture,
        has_placeholders=has_placeholders,
    ))
    return result, logged


def test_provider_failure_is_logged_with_its_cause_not_as_a_bare_message():
    failure = LLMFailure(provider="ollama", kind="http", error_type="HTTPStatusError",
                         message="service unavailable", status=503)
    client = LLMClient(provider_type="ollama")
    client._provider = _FakeProvider(failure=failure)

    result, logged = _translate(client)

    assert result is None
    errors = [message for event, message in logged if event == "llm_api_error"]
    assert errors == [
        "ERROR: LLM API request failed: ollama HTTPStatusError (HTTP 503): service unavailable"
    ]


def test_missing_translation_block_is_not_reported_as_an_api_failure():
    client = LLMClient(provider_type="ollama")
    client._provider = _FakeProvider(
        response=LLMResponse(content="a reply without any translation block"))

    result, logged = _translate(client, has_placeholders=True)

    assert result is None
    errors = [message for event, message in logged if event == "llm_api_error"]
    assert len(errors) == 1
    assert errors[0].startswith("ERROR: LLM call returned no translation (extraction): ")
    assert "API" not in errors[0]


def test_ollama_http_error_is_recorded_on_the_provider(monkeypatch):
    monkeypatch.setattr(ollama_module, "MAX_TRANSLATION_ATTEMPTS", 1)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(ollama_module.asyncio, "sleep", no_sleep)

    def handler(request):
        return httpx.Response(500, json={"error": "model failed to load"})

    provider = OllamaProvider(api_endpoint="http://ollama.test/api/chat", model="index-9b")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(provider.generate("hello"))

    assert result is None
    assert provider.last_failure is not None
    assert provider.last_failure.kind == "http"
    assert provider.last_failure.status == 500
    assert provider.last_failure.error_type == "HTTPStatusError"
    assert provider.last_failure.message == "model failed to load"


def test_ollama_timeout_is_recorded_on_the_provider(monkeypatch):
    monkeypatch.setattr(ollama_module, "MAX_TRANSLATION_ATTEMPTS", 1)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(ollama_module.asyncio, "sleep", no_sleep)

    def handler(request):
        raise httpx.ReadTimeout("no bytes for 600 s", request=request)

    provider = OllamaProvider(api_endpoint="http://ollama.test/api/chat", model="index-9b")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(provider.generate("hello"))

    assert result is None
    assert provider.last_failure.kind == "timeout"
    assert provider.last_failure.status is None
    assert provider.last_failure.error_type == "ReadTimeout"
