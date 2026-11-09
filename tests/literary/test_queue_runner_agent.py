"""The host agent consumes a run request without spawning a translation."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.literary.models import BookRecord
from src.literary.queue import QueueStore
from src.literary.queue_run_control import request_run

from .conftest import make_epub

ROOT = Path(__file__).resolve().parents[2]


def _record(path: Path) -> BookRecord:
    return BookRecord(
        calibre_id=1,
        title="Test Book",
        author="Test Author",
        series="Test Series",
        series_index=1.0,
        languages=["en"],
        formats=["EPUB"],
        epub_path=str(path),
    )


def test_agent_dry_run_consumes_the_request(tmp_path):
    db = tmp_path / "queue.db"
    store = QueueStore(str(db))
    store.add_book(_record(make_epub(tmp_path / "book.epub")))
    store.close()
    request_run(db, mode="next")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/queue_runner_agent.py",
            "--db",
            str(db),
            "--once",
            "--dry-run",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not (tmp_path / "queue.run-request.json").exists()

    info = json.loads((tmp_path / "queue.runner.json").read_text(encoding="utf-8"))
    assert info["dry_run"] is True
    assert info["mode"] == "next"
    assert info["title"] == "Test Book"
    command = info["command"]
    assert command[command.index("--max-books") + 1] == "1"
    assert command[command.index("--parallel") + 1] == "1"

    status = json.loads((tmp_path / "queue.agent.json").read_text(encoding="utf-8"))
    assert status["last_result"] == "dry run"


def test_agent_refuses_a_batch_request(tmp_path):
    db = tmp_path / "queue.db"
    store = QueueStore(str(db))
    store.add_book(_record(make_epub(tmp_path / "book.epub")))
    store.close()
    request_path = tmp_path / "queue.run-request.json"
    request_path.write_text(
        json.dumps({"mode": "all", "requested_at": "2026-11-09T00:00:00+00:00"}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/queue_runner_agent.py",
            "--db",
            str(db),
            "--once",
            "--dry-run",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not request_path.exists()
    assert not (tmp_path / "queue.runner.json").exists()
    status = json.loads((tmp_path / "queue.agent.json").read_text(encoding="utf-8"))
    assert status["last_result"] == "one book per run"
