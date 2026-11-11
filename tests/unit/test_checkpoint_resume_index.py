"""Resume-index convention + reconciliation in ``load_checkpoint``.

The chunk rows are now the source of truth. These tests seed both the chunk
rows and (where relevant) the legacy progress JSON to verify that
``load_checkpoint`` reconciles the two before choosing a resume point.
"""

import json

import pytest

from src.persistence.checkpoint_manager import CheckpointManager


@pytest.fixture
def cm(tmp_path):
    return CheckpointManager(db_path=str(tmp_path / "jobs.db"))


def _set_progress(manager, translation_id, progress):
    conn = manager.db._get_connection()
    conn.execute(
        "UPDATE translation_jobs SET progress = ? WHERE translation_id = ?",
        (json.dumps(progress), translation_id),
    )
    conn.commit()


def _seed_chunks(manager, translation_id, indices):
    for index in indices:
        manager.db.save_chunk(
            translation_id,
            index,
            "x",
            "y",
            status="completed",
        )


@pytest.mark.parametrize("file_type", ["epub", "txt", "srt"])
def test_new_marked_checkpoint_resumes_at_next_unit(cm, file_type):
    cm.start_job("job", file_type, {}, None)
    for index in range(3):
        cm.save_checkpoint(
            translation_id="job",
            chunk_index=index,
            original_text="x",
            translated_text="y",
            total_chunks=10,
            completed_chunks=3,
            failed_chunks=0,
        )
    assert cm.load_checkpoint("job")["resume_from_index"] == 3


def test_legacy_epub_checkpoint_without_marker(cm):
    # Pre-migration EPUB: current_chunk_index was file_idx+1 (the next file),
    # and there is no semantics marker. Reconciliation derives the index from
    # the three completed chunk rows.
    cm.start_job("job", "epub", {}, None)
    _seed_chunks(cm, "job", [0, 1, 2])
    _set_progress(cm, "job", {
        "current_chunk_index": 3,
        "total_chunks": 10,
        "completed_chunks": 3,
        "failed_chunks": 0,
    })
    assert cm.load_checkpoint("job")["resume_from_index"] == 3


def test_legacy_txt_checkpoint_without_marker(cm):
    cm.start_job("job", "txt", {}, None)
    _seed_chunks(cm, "job", [0, 1, 2, 3, 4, 5])
    _set_progress(cm, "job", {
        "current_chunk_index": 5,
        "total_chunks": 10,
        "completed_chunks": 6,
        "failed_chunks": 0,
    })
    assert cm.load_checkpoint("job")["resume_from_index"] == 6


def test_gap_resumes_at_first_missing_chunk(cm):
    cm.start_job("job", "epub", {}, None)
    _seed_chunks(cm, "job", [0, 2])
    # The JSON lies: it claims three completed chunks, but index 1 is missing.
    _set_progress(cm, "job", {
        "current_chunk_index": 2,
        "total_chunks": 10,
        "completed_chunks": 3,
        "failed_chunks": 0,
    })
    assert cm.load_checkpoint("job")["resume_from_index"] == 1
