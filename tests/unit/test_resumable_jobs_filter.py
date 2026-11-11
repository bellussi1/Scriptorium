"""
Tests for the Paused Translations filtering contract.

A row is only resumable when the input file still exists, the job still has
work left and at least one checkpoint chunk survived. Duplicate attempts at
the same source book collapse to the newest one, and books finished in the
literary queue never reappear as paused.
"""

import sqlite3

import pytest

from src.api.blueprints.translation_routes import _queue_finished_translation_ids
from src.persistence.checkpoint_manager import CheckpointManager


@pytest.fixture
def cm(tmp_path, monkeypatch):
    """A CheckpointManager fully contained in tmp_path."""
    monkeypatch.chdir(tmp_path)
    manager = CheckpointManager(db_path=str(tmp_path / 'jobs.db'))
    manager.uploads_dir = tmp_path / 'uploads'
    manager.uploads_dir.mkdir(parents=True, exist_ok=True)
    yield manager
    manager.close()


def _job(
    cm,
    translation_id,
    input_path,
    *,
    status='paused',
    total=10,
    completed=1,
    chunks=2,
    failed=0,
    file_type='epub',
):
    """Create a job with a real input file, chunks and progress metadata."""
    if input_path is not None:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text('source', encoding='utf-8')
    config = {'preserved_input_path': str(input_path)} if input_path else {}
    assert cm.db.create_job(translation_id, file_type, config)
    for index in range(chunks):
        cm.db.save_chunk(
            translation_id, index, f'source {index}', f'target {index}'
        )
    cm.db.update_job_progress(
        translation_id,
        total_chunks=total,
        completed_chunks=completed,
        failed_chunks=failed,
        status=status,
    )
    return config


def _set_updated_at(cm, translation_id, value):
    conn = sqlite3.connect(cm.db.db_path)
    try:
        conn.execute(
            "UPDATE translation_jobs SET updated_at = ? WHERE translation_id = ?",
            (value, translation_id),
        )
        conn.commit()
    finally:
        conn.close()


class TestResumableFilter:
    def test_missing_preserved_input_is_not_resumable(self, cm, tmp_path):
        input_path = tmp_path / 'uploads' / 'gone' / 'Book.epub'
        _job(cm, 'gone', input_path)
        input_path.unlink()

        assert cm.get_resumable_jobs() == []

    def test_finished_progress_is_not_resumable(self, cm, tmp_path):
        _job(
            cm,
            'done',
            tmp_path / 'uploads' / 'done' / 'Book.epub',
            status='interrupted',
            total=2,
            completed=2,
            chunks=2,
        )

        assert cm.get_resumable_jobs() == []

    def test_job_without_any_stored_chunk_is_not_resumable(self, cm, tmp_path):
        _job(
            cm,
            'empty',
            tmp_path / 'uploads' / 'empty' / 'Book.epub',
            chunks=0,
        )

        assert cm.get_resumable_jobs() == []

    def test_duplicate_attempts_collapse_to_the_newest(self, cm, tmp_path):
        _job(cm, 'older', tmp_path / 'uploads' / 'older' / 'Book.epub')
        _job(cm, 'newer', tmp_path / 'uploads' / 'newer' / 'Book.epub')

        _set_updated_at(cm, 'older', '2026-01-01 10:00:00')
        _set_updated_at(cm, 'newer', '2026-01-02 10:00:00')

        ids = [job['translation_id'] for job in cm.get_resumable_jobs()]

        assert ids == ['newer']

    def test_progress_is_rebuilt_from_stored_chunks(self, cm, tmp_path):
        _job(
            cm,
            'drifted',
            tmp_path / 'uploads' / 'drifted' / 'Book.txt',
            total=100,
            completed=90,
            chunks=3,
            file_type='txt',
        )

        job = cm.get_resumable_jobs()[0]

        assert job['progress']['completed_chunks'] == 3
        assert job['checkpoint_chunks'] == 3
        assert job['checkpoint_completed_chunks'] == 3
        assert job['progress_percentage'] == 3

    def test_epub_keeps_the_global_chunk_count_and_reports_files(self, cm, tmp_path):
        _job(
            cm,
            'epub-drift',
            tmp_path / 'uploads' / 'epub-drift' / 'Book.epub',
            total=100,
            completed=90,
            chunks=3,
            file_type='epub',
        )

        job = cm.get_resumable_jobs()[0]

        # EPUB checkpoint rows are files, not chunks; the global counter must
        # not be replaced by the number of translated files.
        assert job['progress']['completed_chunks'] == 90
        assert job['checkpoint_chunks'] == 3
        assert job['checkpoint_files'] == 3
        assert job['checkpoint_completed_chunks'] == 90
        assert job['progress_percentage'] == 90

    def test_healthy_job_remains_resumable(self, cm, tmp_path):
        _job(
            cm,
            'healthy',
            tmp_path / 'uploads' / 'healthy' / 'Book.epub',
            total=10,
            completed=2,
            chunks=2,
        )

        jobs = cm.get_resumable_jobs()

        assert [job['translation_id'] for job in jobs] == ['healthy']
        assert jobs[0]['input_filename'] == 'Book.epub'


class TestQueueFinishedFilter:
    def _queue_db(self, path):
        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                """
                CREATE TABLE books (id INTEGER PRIMARY KEY, status TEXT NOT NULL);
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY,
                    book_id INTEGER NOT NULL,
                    translation_id TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.executemany(
                "INSERT INTO books (id, status) VALUES (?, ?)",
                [(1, 'completed'), (2, 'needs_review'), (3, 'paused')],
            )
            conn.executemany(
                "INSERT INTO jobs (book_id, translation_id) VALUES (?, ?)",
                [(1, 'cli_done'), (2, 'cli_review'), (3, 'cli_paused')],
            )
            conn.commit()
        finally:
            conn.close()

    def test_completed_and_needs_review_ids_are_excluded(self, tmp_path, monkeypatch):
        path = tmp_path / 'queue.db'
        self._queue_db(path)
        monkeypatch.setenv('LITERARY_QUEUE_DB', str(path))

        assert _queue_finished_translation_ids() == {'cli_done', 'cli_review'}

    def test_missing_queue_database_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv('LITERARY_QUEUE_DB', str(tmp_path / 'missing.db'))

        assert _queue_finished_translation_ids() == set()
