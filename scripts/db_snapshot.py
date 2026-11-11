"""Snapshot the live jobs DB and the queue DB with integrity checks.

The live ``jobs.db`` is on a Docker volume, so its snapshot is produced by a
short ``docker compose exec`` inside the app container. The queue DB is on the
host bind mount and is copied with the SQLite backup API. Both snapshots are
checked with ``PRAGMA quick_check`` and recorded in ``data/backups/snapshots.jsonl``.

Usage:
    python scripts/db_snapshot.py --label howling-dark
    python scripts/db_snapshot.py --no-live
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / "data" / "backups"
QUEUE_DB = ROOT / "data" / "literary_queue.db"
COMPOSE_FILE = ROOT / "docker-compose.dev.yml"
MANIFEST = BACKUP_DIR / "snapshots.jsonl"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _quick_check(path: Path) -> str:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        row = con.execute("PRAGMA quick_check").fetchone()
        return str(row[0] if row else "unknown")
    finally:
        con.close()


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(raw[start:])
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _record(kind: str, label: str, path: Path, integrity: str) -> Dict[str, Any]:
    payload = {
        "timestamp": _stamp(),
        "kind": kind,
        "label": label,
        "path": str(path.relative_to(ROOT)),
        "size": path.stat().st_size,
        "integrity": integrity,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def snapshot_queue(label: str) -> Dict[str, Any]:
    if not QUEUE_DB.exists():
        return {"kind": "queue", "ok": False, "error": "queue database not found"}
    suffix = f"-{label}" if label else ""
    path = BACKUP_DIR / f"literary_queue{suffix}-{_stamp()}.db"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{QUEUE_DB.as_posix()}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(str(path))
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    integrity = _quick_check(path)
    record = _record("queue", label, path, integrity)
    return {"kind": "queue", "ok": integrity.lower() == "ok", **record}


def snapshot_live(label: str) -> Dict[str, Any]:
    command = [
        "docker", "compose", "-f", str(COMPOSE_FILE),
        "exec", "-T", "app",
        "python", "-m", "src.literary.cli", "queue", "db-snapshot",
        "--out-dir", "/app/data/backups",
        "--label", label,
        "--json",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception as exc:
        return {"kind": "jobs", "ok": False, "error": str(exc)}
    if completed.returncode != 0:
        return {
            "kind": "jobs",
            "ok": False,
            "error": (completed.stderr or completed.stdout or "").strip()[-800:],
        }
    payload = _parse_json(completed.stdout)
    if not payload:
        return {"kind": "jobs", "ok": False, "error": "no JSON from db-snapshot"}

    container_path = Path(str(payload.get("path") or ""))
    host_path = BACKUP_DIR / container_path.name
    integrity = str(payload.get("integrity") or "unknown")
    if host_path.exists():
        integrity = _quick_check(host_path)
    record = _record("jobs", label, host_path, integrity)
    return {
        "kind": "jobs",
        "ok": integrity.lower() == "ok",
        **record,
        "size": int(payload.get("size") or record["size"]),
    }


def prune(keep_daily: int = 7, keep_labeled: int = 1) -> List[str]:
    """Keep the last N daily snapshots and N per book label."""
    if not MANIFEST.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    keep: set[str] = set()
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for record in records:
        key = (record.get("kind"), record.get("label") or "")
        groups.setdefault(key, []).append(record)
    for (_, label), items in groups.items():
        limit = keep_daily if not label else keep_labeled
        for record in items[-limit:]:
            keep.add(str(record.get("path") or ""))

    removed: List[str] = []
    for record in records:
        relative = str(record.get("path") or "")
        if relative in keep:
            continue
        path = ROOT / relative
        try:
            if path.exists():
                path.unlink()
                removed.append(relative)
        except OSError:
            continue
    with MANIFEST.open("w", encoding="utf-8") as handle:
        for record in records:
            if str(record.get("path") or "") in keep:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="")
    parser.add_argument("--no-live", action="store_true")
    parser.add_argument("--no-queue", action="store_true")
    parser.add_argument("--keep-daily", type=int, default=7)
    parser.add_argument("--keep-labeled", type=int, default=1)
    args = parser.parse_args()

    label = _slug(args.label)
    results: List[Dict[str, Any]] = []
    if not args.no_queue:
        results.append(snapshot_queue(label))
    if not args.no_live:
        results.append(snapshot_live(label))
    removed = prune(args.keep_daily, args.keep_labeled)
    print(json.dumps({
        "label": label,
        "snapshots": results,
        "removed": removed,
        "ok": all(item.get("ok") for item in results),
    }, ensure_ascii=False, indent=2))
    return 0 if all(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
