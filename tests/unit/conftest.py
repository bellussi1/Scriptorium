"""Keep unit tests off the live literary queue.

The translate routes refuse to start while the host queue runner is alive, and they read that
state from ``LITERARY_QUEUE_DB`` (default: the live queue). Each test gets its own empty queue
path, so a translation running on the real queue cannot turn these tests into 409 failures.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_literary_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("LITERARY_QUEUE_DB", str(tmp_path / "literary_queue.db"))
