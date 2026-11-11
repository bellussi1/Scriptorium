"""Tests for live jobs DB recovery from a healthy snapshot."""

import sqlite3
from pathlib import Path

from src.persistence.recovery import recover_live_db_if_needed


def _make_db(path, value):
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE marker (value TEXT)")
        conn.execute("INSERT INTO marker VALUES (?)", (value,))
        conn.commit()
    finally:
        conn.close()


def _corrupt(path):
    with open(path, "r+b") as handle:
        handle.seek(0)
        handle.write(b"\x00" * 32)
        handle.flush()


def test_corrupt_live_db_is_replaced_by_newest_healthy_snapshot(tmp_path):
    live = tmp_path / "state" / "jobs.db"
    live.parent.mkdir()
    backups = tmp_path / "backups"
    backups.mkdir()
    snapshot = backups / "jobs-20260101T000000Z.db"
    _make_db(snapshot, "snapshot")
    _make_db(live, "live")
    _corrupt(live)

    result = recover_live_db_if_needed(live, backups)

    assert result["status"] == "restored"
    assert result["integrity"].lower() == "ok"
    conn = sqlite3.connect(live)
    try:
        assert conn.execute("SELECT value FROM marker").fetchone()[0] == "snapshot"
    finally:
        conn.close()
    assert Path(result["corrupt_copy"]).exists()


def test_corrupt_live_db_without_snapshot_is_left_for_a_loud_failure(tmp_path):
    live = tmp_path / "jobs.db"
    backups = tmp_path / "backups"
    backups.mkdir()
    _make_db(live, "live")
    _corrupt(live)

    result = recover_live_db_if_needed(live, backups)

    assert result["status"] == "corrupt"
    assert live.exists()
