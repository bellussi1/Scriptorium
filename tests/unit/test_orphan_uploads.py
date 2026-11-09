"""Orphan-upload cleanup must not delete resumable queue checkpoints."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.persistence.checkpoint_manager import CheckpointManager


@pytest.fixture
def cm(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = CheckpointManager(db_path=str(tmp_path / "jobs.db"))
    manager.uploads_dir = tmp_path / "uploads"
    manager.uploads_dir.mkdir(parents=True, exist_ok=True)
    yield manager
    manager.close()


def _queue_db(path: Path, translation_id: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE jobs (translation_id TEXT)")
        conn.execute("INSERT INTO jobs VALUES (?)", (translation_id,))
        conn.commit()
    finally:
        conn.close()


def test_keeps_a_cli_checkpoint_owned_by_the_literary_queue(cm, tmp_path: Path):
    _queue_db(tmp_path / "literary_queue.db", "cli_abc")
    keep = cm.uploads_dir / "cli_abc"
    keep.mkdir()
    orphan = cm.uploads_dir / "cli_orphan"
    orphan.mkdir()

    assert cm.cleanup_orphan_uploads() == 1
    assert keep.exists()
    assert not orphan.exists()


def test_keeps_a_legacy_trans_job_folder(cm):
    keep = cm.uploads_dir / "trans_legacy"
    keep.mkdir()
    assert cm.db.create_job("trans_legacy", "txt", {})

    assert cm.cleanup_orphan_uploads() == 0
    assert keep.exists()
