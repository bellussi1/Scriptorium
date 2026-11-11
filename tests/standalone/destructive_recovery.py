"""Destructive reliability checks that do not need the translation model.

Covers the recovery path for a corrupt live jobs DB on a copy: healthy,
corrupt with a healthy snapshot, corrupt without a snapshot, corrupt newest
snapshot with an older healthy one, and a truncated file. Never touches the
live ``data/jobs.db`` or the Docker volume.

Run from the repository root:

    python tests/standalone/destructive_recovery.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.persistence.recovery import _integrity, recover_live_db_if_needed

STAMP = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
WORK = ROOT / "data" / "tmp" / f"destructive-recovery-{STAMP}"


def _healthy_snapshot() -> Path:
    backups = ROOT / "data" / "backups"
    candidates = sorted(
        backups.glob("jobs-*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        name = candidate.name
        if name.startswith(("jobs-corrupt-", "jobs-old-", "jobs-pre-volume-")):
            continue
        if _integrity(candidate).lower() == "ok":
            return candidate
    raise SystemExit("no healthy jobs snapshot available in data/backups")


def _corrupt(path: Path, *, truncate: bool = False) -> None:
    data = path.read_bytes()
    if truncate:
        path.write_bytes(data[: max(64, len(data) // 8)])
        return
    damaged = bytearray(data)
    for index in range(min(256, len(damaged))):
        damaged[index] = (index * 37 + 11) % 256
    path.write_bytes(bytes(damaged))


def _copy(src: Path, dst: Path, *, mtime: float | None = None) -> Path:
    shutil.copy2(src, dst)
    if mtime is not None:
        os.utime(dst, (mtime, mtime))
    return dst


def _scenario(name: str, live: Path, backups: Path) -> dict:
    before = _integrity(live)
    result = recover_live_db_if_needed(str(live), str(backups))
    after = _integrity(live)
    corrupt_copies = sorted(backups.glob("jobs-corrupt-*.db"))
    record = {
        "name": name,
        "before": before,
        "status": result.get("status"),
        "snapshot": result.get("snapshot"),
        "after": after,
        "corrupt_copies": [path.name for path in corrupt_copies],
        "error": result.get("error"),
    }
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def main() -> int:
    healthy = _healthy_snapshot()
    WORK.mkdir(parents=True, exist_ok=True)
    print(f"healthy snapshot: {healthy}")
    print(f"work dir: {WORK}")

    results: list[dict] = []

    # 1. Healthy live DB: no restore, no corrupt copy.
    case = WORK / "healthy"
    case.mkdir()
    live = _copy(healthy, case / "jobs.db")
    backups = case / "backups"
    backups.mkdir()
    _copy(healthy, backups / "jobs-good.db")
    record = _scenario("healthy", live, backups)
    assert record["status"] == "ok", record
    assert record["after"].lower() == "ok", record
    assert not record["corrupt_copies"], record
    results.append(record)

    # 2. Corrupt live DB with one healthy snapshot: restore.
    case = WORK / "restore"
    case.mkdir()
    live = _copy(healthy, case / "jobs.db")
    backups = case / "backups"
    backups.mkdir()
    snapshot = _copy(healthy, backups / "jobs-good.db")
    _corrupt(live)
    record = _scenario("corrupt-with-snapshot", live, backups)
    assert record["status"] == "restored", record
    assert record["snapshot"] == str(snapshot), record
    assert record["after"].lower() == "ok", record
    assert record["corrupt_copies"], record
    results.append(record)

    # 3. Corrupt live DB without any snapshot: fail closed, keep the file.
    case = WORK / "no-snapshot"
    case.mkdir()
    live = _copy(healthy, case / "jobs.db")
    backups = case / "backups"
    backups.mkdir()
    _corrupt(live)
    record = _scenario("corrupt-without-snapshot", live, backups)
    assert record["status"] == "corrupt", record
    assert record["after"].lower() != "ok", record
    assert record["corrupt_copies"], record
    results.append(record)

    # 4. Corrupt newest snapshot, healthy older one: skip the bad one.
    case = WORK / "newest-bad"
    case.mkdir()
    live = _copy(healthy, case / "jobs.db")
    backups = case / "backups"
    backups.mkdir()
    older = _copy(healthy, backups / "jobs-older-good.db", mtime=time.time() - 3600)
    newest = _copy(healthy, backups / "jobs-newest-bad.db", mtime=time.time())
    _corrupt(newest)
    _corrupt(live)
    record = _scenario("corrupt-newest-snapshot", live, backups)
    assert record["status"] == "restored", record
    assert record["snapshot"] == str(older), record
    assert record["after"].lower() == "ok", record
    results.append(record)

    # 5. Truncated live DB: restore from a healthy snapshot.
    case = WORK / "truncated"
    case.mkdir()
    live = _copy(healthy, case / "jobs.db")
    backups = case / "backups"
    backups.mkdir()
    _copy(healthy, backups / "jobs-good.db")
    _corrupt(live, truncate=True)
    record = _scenario("truncated-with-snapshot", live, backups)
    assert record["status"] == "restored", record
    assert record["after"].lower() == "ok", record
    results.append(record)

    summary = WORK / "summary.json"
    summary.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPASS: {len(results)} recovery scenarios; summary={summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
