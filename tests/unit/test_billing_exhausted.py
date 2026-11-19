"""An exhausted wallet must abort the run, not save the source text.

The Rain Wild run lost 15 chapters to a silent fallback: Gemini answered
HTTP 402 ("prepayment credits are depleted"), the provider swallowed the
error, and the chunk fallback kept the English text as if it were
translated. These tests pin the new contract: billing errors propagate.
"""
from __future__ import annotations

import pytest

from src.core.epub.translation_metrics import TranslationMetrics
from src.core.epub.xhtml_translator import translate_chunk_with_fallback
from src.core.llm.exceptions import BillingExhaustedError


class _EmptyWalletClient:
    """Fake LLM client whose wallet is empty.

    The first call can return None (an ordinary chunk failure); from then on
    every call raises, as a real provider does once credit runs out.
    """

    def __init__(self, fail_first_with_none: bool = False):
        self.calls = 0
        self.fail_first_with_none = fail_first_with_none

    async def generate(self, prompt, system_prompt=None):
        self.calls += 1
        if self.fail_first_with_none and self.calls == 1:
            return None
        raise BillingExhaustedError(
            "prepayment credits are depleted", provider="gemini"
        )

    def extract_translation(self, content):
        return content


async def _translate_chunk(client):
    return await translate_chunk_with_fallback(
        chunk_text="A paragraph of ordinary prose, long enough to be sent to the model.",
        local_tag_map={"[id0]": "<p>"},
        global_indices=[0],
        source_language="English",
        target_language="Portuguese",
        model_name="fake",
        llm_client=client,
        stats=TranslationMetrics(),
        log_callback=None,
        max_retries=1,
    )


@pytest.mark.asyncio
async def test_billing_error_in_phase_1_aborts_the_chunk():
    with pytest.raises(BillingExhaustedError):
        await _translate_chunk(_EmptyWalletClient())


@pytest.mark.asyncio
async def test_billing_error_in_phase_2_does_not_fall_back_to_source_text():
    # First call fails like an ordinary chunk failure, so the flow reaches the
    # Phase 2 fallback machinery; the billing error raised there must escape
    # the broad ``except Exception`` that used to swallow it.
    with pytest.raises(BillingExhaustedError):
        await _translate_chunk(_EmptyWalletClient(fail_first_with_none=True))


def test_litellm_classifies_billing_failures():
    from src.core.llm.providers.litellm import _is_billing_error

    assert _is_billing_error(["litellm.exceptions.BudgetExceededError"], "")
    assert _is_billing_error([], "your credit balance is too low, please add funds")
    assert _is_billing_error([], "Error code: 402 - payment required")
    assert not _is_billing_error([], "connection reset by peer")
    assert not _is_billing_error(["litellm.exceptions.Timeout"], "")


def test_exception_is_exported_from_the_llm_package():
    import src.core.llm as llm

    assert "BillingExhaustedError" in llm.__all__
    assert llm.BillingExhaustedError is BillingExhaustedError


@pytest.mark.asyncio
async def test_chunk_loop_aborts_and_keeps_the_failed_chunk_resumable(
    monkeypatch, tmp_path
):
    """The run stops at the chunk that hit the empty wallet.

    The chunks translated before it are persisted, the failed one is left
    pending (so a resume restarts there), and nothing is recorded as
    untranslated source text.
    """
    import src.core.epub.xhtml_translator as xt
    from src.core.epub.xhtml_translation_state import (
        CHUNK_PENDING,
        CHUNK_TRANSLATED,
        CHUNK_UNTRANSLATED,
    )
    from src.persistence.checkpoint_manager import CheckpointManager

    async def fake_generate(chunk_text, **kwargs):
        if "second" in chunk_text:
            raise BillingExhaustedError("prepayment credits are depleted", provider="gemini")
        return "Primeiro paragrafo traduzido."

    monkeypatch.setattr(xt, "generate_translation_request", fake_generate)

    manager = CheckpointManager(db_path=str(tmp_path / "jobs.db"))
    manager.uploads_dir = tmp_path / "uploads"
    manager.uploads_dir.mkdir(parents=True, exist_ok=True)

    chunks = [
        {"text": text, "local_tag_map": {}, "global_indices": []}
        for text in ("The first paragraph.", "The second paragraph.", "The third paragraph.")
    ]
    translation_id, file_href = "billing_job", "OEBPS/chapter8.xhtml"

    with pytest.raises(BillingExhaustedError):
        await xt._translate_all_chunks_with_checkpoint(
            chunks=chunks,
            source_language="English",
            target_language="Portuguese",
            model_name="fake",
            llm_client=object(),
            max_retries=1,
            context_manager=None,
            placeholder_format=("[id", "]"),
            checkpoint_manager=manager,
            translation_id=translation_id,
            file_href=file_href,
            file_path=file_href,
            parallel_workers=1,
        )

    state = manager.load_xhtml_partial_state(translation_id, file_href)
    assert state is not None
    assert state.validate() is True
    assert state.chunk_statuses == [CHUNK_TRANSLATED, CHUNK_PENDING, CHUNK_PENDING]
    assert CHUNK_UNTRANSLATED not in state.chunk_statuses
    assert state.current_chunk_index == 1


def test_queue_runner_mirrors_the_cli_billing_exit_code():
    from src.core.llm.exceptions import BILLING_EXHAUSTED_EXIT_CODE
    from src.literary import queue_runner

    assert queue_runner.BILLING_EXHAUSTED_EXIT_CODE == BILLING_EXHAUSTED_EXIT_CODE
    assert BILLING_EXHAUSTED_EXIT_CODE not in (0, 1, 2)


def test_cli_exits_with_the_billing_code_and_notifies(monkeypatch, tmp_path):
    """translate.py used to log the failure and exit 0, so the queue runner went
    on to repair and finalize a half-translated output."""
    import runpy
    import sys
    from pathlib import Path

    import src.core.adapters as adapters
    import src.persistence.checkpoint_manager as checkpoint_manager
    import src.utils.notifier as notifier
    from src.core.llm.exceptions import BILLING_EXHAUSTED_EXIT_CODE

    async def fake_translate_file(**kwargs):
        raise BillingExhaustedError("prepayment credits are depleted", provider="gemini")

    real_manager = checkpoint_manager.CheckpointManager
    events = []
    monkeypatch.setattr(adapters, "translate_file", fake_translate_file)
    monkeypatch.setattr(
        checkpoint_manager,
        "CheckpointManager",
        lambda *args, **kwargs: real_manager(db_path=str(tmp_path / "jobs.db")),
    )
    monkeypatch.setattr(notifier, "notify", lambda event, payload=None: events.append(event))

    source = tmp_path / "book.txt"
    source.write_text("Hello world.", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "translate.py", "-i", str(source), "-o", str(tmp_path / "out.txt"),
        "--provider", "gemini", "--gemini_api_key", "YOUR_API_KEY_HERE",
    ])

    script = Path(__file__).resolve().parents[2] / "translate.py"
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(script), run_name="__main__")

    assert exit_info.value.code == BILLING_EXHAUSTED_EXIT_CODE
    assert events == [notifier.EVENT_FAILURE]
