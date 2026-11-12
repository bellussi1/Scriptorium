"""The fallback repair: inventory of flagged chunks, refusal rules and the apply path.

No database, Docker or network: the store, the checkpoint manager and the
subprocess runner are replaced with fakes.
"""
import argparse
import json
from types import SimpleNamespace

import pytest

from src.literary import cli, fallback_repair, queue_runner


PROGRESS = {
    "epub_degraded_units": {
        "OEBPS/ch1.xhtml": [4, 7],
        "OEBPS/ch2.xhtml": [1],
    },
    "epub_fallback_units": {
        "OEBPS/ch1.xhtml": {
            "4": {"reason": "placeholder", "attempts": 2, "causes": ["placeholder", "placeholder"]},
            "9": {"reason": "api", "attempts": 3, "causes": ["api", "api", "api"]},
        },
        "OEBPS/ch2.xhtml": {
            "1": {"reason": "raw", "attempts": 3, "causes": ["extraction", "extraction"]},
        },
    },
    "epub_unfinished_units": {"OEBPS/ch3.xhtml": [0, 1]},
}


def test_entries_merge_recorded_reasons_with_degraded_chunks():
    entries = fallback_repair.collect_fallback_entries(PROGRESS)

    keys = [(entry.href, entry.index) for entry in entries]
    assert keys == [
        ("OEBPS/ch1.xhtml", 4),
        ("OEBPS/ch1.xhtml", 7),
        ("OEBPS/ch1.xhtml", 9),
        ("OEBPS/ch2.xhtml", 1),
    ]
    by_key = {(entry.href, entry.index): entry for entry in entries}
    assert by_key[("OEBPS/ch1.xhtml", 4)].reason == "placeholder"
    assert by_key[("OEBPS/ch1.xhtml", 4)].degraded is True
    assert by_key[("OEBPS/ch1.xhtml", 9)].degraded is False  # untranslated, not degraded
    assert by_key[("OEBPS/ch1.xhtml", 7)].reason == "unrecorded"  # written before the reasons existed


def test_summary_counts_by_reason_and_file():
    summary = fallback_repair.summarize_fallbacks(fallback_repair.collect_fallback_entries(PROGRESS))

    assert summary["chunks"] == 4
    assert summary["files"] == 2
    assert summary["by_reason"] == {"api": 1, "placeholder": 1, "raw": 1, "unrecorded": 1}


def test_empty_progress_has_nothing_to_repair():
    assert fallback_repair.collect_fallback_entries({}) == []


@pytest.mark.parametrize("book_status", ["needs_review", "paused"])
def test_repair_is_allowed_on_finished_or_paused_books(book_status):
    assert fallback_repair.repair_refusal(book_status, "paused") is None


@pytest.mark.parametrize("book_status", ["translating", "approved", "pending"])
def test_repair_is_refused_for_other_book_states(book_status):
    assert "repair runs only" in fallback_repair.repair_refusal(book_status, "paused")


@pytest.mark.parametrize("job_state", ["running", "preparing"])
def test_repair_is_refused_while_a_job_is_busy(job_state):
    assert "wait until it stops" in fallback_repair.repair_refusal("needs_review", job_state)


def test_repair_command_keeps_the_resume_and_adds_the_flag():
    base = ["docker", "compose", "translate.py", "--translation-id", "cli_1"]

    command = fallback_repair.repair_command(base)

    assert command == base + ["--retry-token-aligned"]
    assert base == ["docker", "compose", "translate.py", "--translation-id", "cli_1"]


def test_run_repair_returns_the_exit_code_of_the_runner():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=3)

    code = fallback_repair.run_repair(["translate.py", "--translation-id", "cli_1"],
                                      runner=runner, cwd="/repo")

    assert code == 3
    assert calls == [(["translate.py", "--translation-id", "cli_1", "--retry-token-aligned"],
                      {"cwd": "/repo", "check": False})]


class _FakeStore:
    book = None
    job = {"translation_id": "cli_1", "state": "paused"}

    def __init__(self, db_path):
        self.db_path = db_path

    def get_book(self, book_id):
        return self.book

    def latest_job(self, book_id):
        return self.job

    def close(self):
        return None


class _FakeManager:
    progress = PROGRESS

    def __init__(self, db_path):
        self.db_path = db_path

    def get_job(self, translation_id):
        return {"progress": self.progress}


@pytest.fixture
def repair_env(monkeypatch):
    book = SimpleNamespace(id=11, title="Kingdoms of Death", status="needs_review",
                           model="index-translate-9b", provider="ollama")
    _FakeStore.book = book
    _FakeStore.job = {"translation_id": "cli_1", "state": "paused"}
    _FakeManager.progress = PROGRESS
    monkeypatch.setattr(cli, "QueueStore", _FakeStore)

    import src.persistence.checkpoint_manager as checkpoint_module
    monkeypatch.setattr(checkpoint_module, "CheckpointManager", _FakeManager)
    monkeypatch.setattr(queue_runner, "_compile_assets", lambda book, root: {})
    monkeypatch.setattr(queue_runner, "resolve_model", lambda model: model)
    monkeypatch.setattr(queue_runner, "output_name", lambda book: "kingdoms.epub")
    monkeypatch.setattr(queue_runner, "_translation_command",
                        lambda book, model, provider, assets, output, parallel_workers=0,
                        translation_id="": ["docker", "translate.py", "--translation-id", translation_id])

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _args(**overrides):
    values = {"db": "unused.db", "book_id": 11, "apply": False, "parallel": 0,
              "resources_root": "literary-resources"}
    values.update(overrides)
    return argparse.Namespace(**values)


def test_dry_run_lists_the_flagged_chunks_and_runs_nothing(repair_env, capsys):
    code = cli.cmd_queue_retranslate_fallbacks(_args())

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["dry_run"] is True
    assert report["flagged"]["chunks"] == 4
    assert report["refusal"] is None
    assert repair_env == []


def test_apply_resumes_the_checkpoint_with_the_retry_flag(repair_env, capsys):
    code = cli.cmd_queue_retranslate_fallbacks(_args(apply=True))

    assert code == 0
    assert len(repair_env) == 1
    command, kwargs = repair_env[0]
    assert command == ["docker", "translate.py", "--translation-id", "cli_1", "--retry-token-aligned"]
    assert kwargs["check"] is False


def test_apply_is_refused_while_the_book_is_translating(repair_env, capsys):
    _FakeStore.book = SimpleNamespace(id=11, title="Kingdoms of Death", status="translating",
                                      model="m", provider="ollama")

    code = cli.cmd_queue_retranslate_fallbacks(_args(apply=True))

    assert code == 2
    assert repair_env == []
    assert "repair runs only" in json.loads(capsys.readouterr().out)["error"]


def test_apply_with_nothing_flagged_does_not_start_a_run(repair_env, capsys):
    _FakeManager.progress = {"epub_unfinished_units": {}}

    code = cli.cmd_queue_retranslate_fallbacks(_args(apply=True))

    assert code == 0
    assert repair_env == []
    assert "nothing to repair" in json.loads(capsys.readouterr().out)["message"]
