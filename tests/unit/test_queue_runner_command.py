"""The queue runner's translation command carries resume and slot options."""
from types import SimpleNamespace

from src.literary.queue_runner import _translation_command


def _book():
    return SimpleNamespace(source_path="/library/Test Author/Test Book/test.epub")


def _assets():
    return {
        "glossary_container": "/app/data/compiled/test.json",
        "style_container": "test-style.yaml",
    }


def test_command_includes_parallel_slots_and_resume_id():
    command = _translation_command(
        _book(), "model", "ollama", _assets(), "Test Book (pt-BR).epub",
        parallel_workers=2,
        translation_id="cli_test",
    )

    assert "OLLAMA_PARALLEL_TRANSLATIONS=2" in command
    assert command[-4:] == ["--parallel", "2", "--translation-id", "cli_test"]


def test_command_stays_sequential_by_default():
    command = _translation_command(
        _book(), "model", "ollama", _assets(), "Test Book (pt-BR).epub"
    )

    assert "OLLAMA_PARALLEL_TRANSLATIONS=1" not in command
    assert "--parallel" not in command
    assert "--translation-id" not in command
