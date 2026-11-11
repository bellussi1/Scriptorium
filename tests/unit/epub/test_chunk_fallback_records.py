"""Every chunk that leaves the normal path is recorded with its reason and attempt count.

translate_chunk_with_fallback is driven by a scripted fake for the LLM call, so
no request is made.
"""
import asyncio

import pytest

from src.core.epub import xhtml_translator
from src.core.epub.translation_metrics import TranslationMetrics
from src.core.epub.xhtml_translation_state import CHUNK_TOKEN_ALIGNED, CHUNK_UNTRANSLATED


CHUNK = "Hello [id0] world"
TAG_MAP = {"[id0]": "<b>"}


def _script(monkeypatch, replies):
    """Replace the LLM call with scripted replies: (text, cause, raw_used) per call."""
    calls = []

    async def fake_generate(chunk_text, **kwargs):
        calls.append(kwargs)
        text, cause, raw_used = replies.pop(0)
        info = kwargs.get("attempt_info")
        if text is None and info is not None:
            info["cause"] = cause
            info["detail"] = f"scripted {cause}"
        if raw_used and info is not None:
            info["raw_used"] = True
        return text

    monkeypatch.setattr(xhtml_translator, "generate_translation_request", fake_generate)
    return calls


def _translate(stats):
    return asyncio.run(xhtml_translator.translate_chunk_with_fallback(
        chunk_text=CHUNK,
        local_tag_map=TAG_MAP,
        global_indices=[0],
        source_language="English",
        target_language="Portuguese (Brazil)",
        model_name="index-9b",
        llm_client=None,
        stats=stats,
        max_retries=2,
        placeholder_format=("[", "]"),
        chunk_index=0,
    ))


def test_first_try_success_records_no_fallback(monkeypatch):
    _script(monkeypatch, [("Olá [id0] mundo", None, False)])
    stats = TranslationMetrics()

    _translate(stats)

    assert stats.chunk_fallbacks == {}
    assert stats.chunk_outcomes[0] != CHUNK_TOKEN_ALIGNED


def test_placeholder_loss_is_recorded_as_placeholder_after_alignment(monkeypatch):
    # Both replies lose the placeholder; the first reply is aligned without a new call.
    calls = _script(monkeypatch, [("Olá mundo", None, False), ("Olá mundo", None, False)])
    stats = TranslationMetrics()

    result = _translate(stats)

    assert len(calls) == 2
    assert stats.chunk_outcomes[0] == CHUNK_TOKEN_ALIGNED
    assert stats.chunk_fallbacks == {
        0: {"reason": "placeholder", "attempts": 2, "causes": ["placeholder", "placeholder"]},
    }
    assert "[id0]" in result or "<b>" in result


def test_raw_reply_is_recorded_as_raw_with_every_attempt(monkeypatch):
    # Two replies have no translation block; the clean re-translation is accepted raw.
    _script(monkeypatch, [
        (None, "extraction", False),
        (None, "extraction", False),
        ("Olá mundo", None, True),
    ])
    stats = TranslationMetrics()

    _translate(stats)

    assert stats.chunk_outcomes[0] == CHUNK_TOKEN_ALIGNED
    assert stats.chunk_fallbacks == {
        0: {"reason": "raw", "attempts": 3, "causes": ["extraction", "extraction"]},
    }


def test_no_reply_text_at_all_is_recorded_as_api_and_kept_untranslated(monkeypatch):
    _script(monkeypatch, [
        (None, "api", False),
        (None, "api", False),
        (None, "api", False),
    ])
    stats = TranslationMetrics()

    result = _translate(stats)

    assert stats.chunk_outcomes[0] == CHUNK_UNTRANSLATED
    assert stats.chunk_fallbacks == {
        0: {"reason": "api", "attempts": 3, "causes": ["api", "api", "api"]},
    }
    assert "Hello" in result  # the source text is kept


def test_a_later_attempt_overwrites_the_record_of_the_same_chunk():
    stats = TranslationMetrics()

    stats.record_chunk_fallback(3, "placeholder", 2, ["placeholder", "placeholder"])
    stats.record_chunk_fallback(3, "api", 3, ["api", "api", "api"])
    stats.record_chunk_fallback(None, "api", 1, ["api"])

    assert stats.chunk_fallbacks == {3: {"reason": "api", "attempts": 3, "causes": ["api", "api", "api"]}}


@pytest.mark.parametrize("bad_record", [
    {"reason": "unknown", "attempts": 1, "causes": []},
    "not-a-dict",
])
def test_state_validation_rejects_unknown_reasons(bad_record):
    from src.core.epub.xhtml_translation_state import XHTMLTranslationState

    state = _make_state(chunk_fallbacks={"0": bad_record})

    assert state.validate() is False


def _make_state(chunk_fallbacks=None, chunk_statuses=None):
    from src.core.epub.xhtml_translation_state import XHTMLTranslationState

    return XHTMLTranslationState(
        file_path="chapter.xhtml",
        translation_id="cli_test",
        file_href="OEBPS/chapter.xhtml",
        source_language="English",
        target_language="Portuguese (Brazil)",
        model_name="index-9b",
        max_tokens_per_chunk=100,
        max_retries=2,
        chunks=[
            {"text": CHUNK, "local_tag_map": TAG_MAP, "global_indices": [0]},
            {"text": "Plain.", "local_tag_map": {}, "global_indices": []},
        ],
        global_tag_map={"[id0]": "<b>"},
        placeholder_format=("[", "]"),
        translated_chunks=["Olá [id0] mundo", "Simples."],
        current_chunk_index=2,
        original_body_html="",
        doc_metadata={},
        stats={},
        created_at="2026-11-11T00:00:00Z",
        updated_at="2026-11-11T00:00:00Z",
        chunk_statuses=chunk_statuses,
        chunk_fallbacks=chunk_fallbacks,
    )


def test_fallback_records_round_trip_through_the_partial_state():
    from src.core.epub.xhtml_translation_state import XHTMLTranslationState

    record = {"reason": "raw", "attempts": 3, "causes": ["extraction", "extraction"]}
    state = _make_state(chunk_fallbacks={"0": record},
                        chunk_statuses=[CHUNK_TOKEN_ALIGNED, "translated"])

    restored = XHTMLTranslationState.from_dict(state.to_dict())

    assert restored.chunk_fallbacks == {"0": record}
    assert restored.validate() is True


def test_legacy_state_without_fallback_records_loads_with_none():
    from src.core.epub.xhtml_translation_state import XHTMLTranslationState

    payload = _make_state().to_dict()
    payload.pop("chunk_fallbacks")

    restored = XHTMLTranslationState.from_dict(payload)

    assert restored.chunk_fallbacks is None
    assert restored.validate() is True


def test_high_failure_warning_waits_for_a_real_sample():
    # The metrics are per XHTML file: 5 chunks are too few to call a rate.
    stats = TranslationMetrics()
    stats.processed_chunks = 5
    stats.token_alignment_used = 3

    assert stats.check_quality_warning() is None

    stats.processed_chunks = 20
    assert stats.check_quality_warning() is not None


def test_fallback_index_is_persisted_on_the_job_and_survives_file_completion(tmp_path):
    from src.persistence.checkpoint_manager import CheckpointManager

    manager = CheckpointManager(db_path=str(tmp_path / "jobs.db"))
    try:
        manager.db.create_job("cli_fb", "epub", {"file_path": "x.epub"})
        index = {"OEBPS/ch1.xhtml": {"4": {"reason": "raw", "attempts": 3,
                                            "causes": ["extraction", "extraction"]}}}

        manager.db.save_checkpoint_atomic(
            translation_id="cli_fb", chunk_index=0, original_text="", translated_text="ok",
            chunk_status="completed", derive_counts=False,
            degraded_units={"OEBPS/ch1.xhtml": [4]}, fallback_units=index)
        manager.db.save_checkpoint_atomic(
            translation_id="cli_fb", chunk_index=1, original_text="", translated_text="ok",
            chunk_status="completed", derive_counts=False)

        progress = manager.get_job("cli_fb")["progress"]
        assert progress["epub_fallback_units"] == index
        assert progress["epub_degraded_units"] == {"OEBPS/ch1.xhtml": [4]}
    finally:
        manager.close()


class _CapturingCheckpoints:
    """Keeps the last partial state saved for each file, like the real checkpoint manager."""

    def __init__(self):
        self.saved = None

    def save_xhtml_partial_state(self, translation_id, file_href, state):
        self.saved = state
        return True


def test_chunk_loop_saves_the_fallback_and_a_repair_pass_clears_it(monkeypatch):
    chunks = [
        {"text": CHUNK, "local_tag_map": TAG_MAP, "global_indices": [0]},
        {"text": "Plain text.", "local_tag_map": {}, "global_indices": []},
    ]
    checkpoints = _CapturingCheckpoints()

    def run(**kwargs):
        return asyncio.run(xhtml_translator._translate_all_chunks_with_checkpoint(
            chunks, "English", "Portuguese (Brazil)", "index-9b", None, 2, None,
            ("[", "]"), checkpoint_manager=checkpoints, translation_id="cli_fb",
            file_href="OEBPS/ch1.xhtml", file_path="ch1.xhtml", global_tag_map=TAG_MAP,
            **kwargs))

    # First pass: chunk 0 loses its placeholder twice and is aligned; chunk 1 is clean.
    _script(monkeypatch, [
        ("Olá mundo", None, False),
        ("Olá mundo", None, False),
        ("Texto simples.", None, False),
    ])
    run()

    state = checkpoints.saved
    assert state.chunk_statuses == [CHUNK_TOKEN_ALIGNED, "translated"]
    assert state.chunk_fallbacks == {
        "0": {"reason": "placeholder", "attempts": 2, "causes": ["placeholder", "placeholder"]},
    }

    # Repair pass, resumed from that state: the flagged chunk is translated cleanly.
    _script(monkeypatch, [("Olá [id0] mundo", None, False)])
    run(translated_chunks=state.translated_chunks, chunk_statuses=state.chunk_statuses,
        start_chunk_index=state.current_chunk_index, chunk_fallbacks=state.chunk_fallbacks,
        retry_token_aligned=True)

    repaired = checkpoints.saved
    assert repaired.chunk_statuses == ["translated", "translated"]
    assert repaired.chunk_fallbacks == {}
    assert repaired.validate() is True
