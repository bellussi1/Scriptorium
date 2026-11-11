"""Independent watchdog for the literary translation run.

It never writes the queue or the live jobs database. Every interval it reads
the queue DB, the read-only jobs mirror, the app container process list and the
live DB health, then writes ``data/literary_queue.health.json`` atomically.

A stall is declared when the active job has not persisted a checkpoint for
``--stall-minutes``. ``--terminate`` is opt-in: it sends SIGTERM to the
translate process, but it does not change the queue state or start a new book.

Usage:
    python scripts/watch_translation.py --interval 30 --stall-minutes 10
    python scripts/watch_translation.py --once
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
QUEUE_DB = ROOT / "data" / "literary_queue.db"
MIRROR_DB = ROOT / "data" / "jobs.mirror.db"
MIRROR_JSON = ROOT / "data" / "jobs.mirror.json"
HEALTH_PATH = ROOT / "data" / "literary_queue.health.json"
COMPOSE_FILE = ROOT / "docker-compose.dev.yml"
RUNNING_STATES = {"preparing", "translating", "reviewing", "validating"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


def _write_health(payload: Dict[str, Any]) -> None:
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEALTH_PATH.with_name(HEALTH_PATH.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, HEALTH_PATH)


def _active_book() -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not QUEUE_DB.exists():
        return None, None
    con = sqlite3.connect(f"file:{QUEUE_DB.as_posix()}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in RUNNING_STATES)
        book = con.execute(
            f"SELECT * FROM books WHERE status IN ({placeholders}) "
            "ORDER BY updated_at DESC LIMIT 1",
            tuple(RUNNING_STATES),
        ).fetchone()
        if not book:
            return None, None
        job = con.execute(
            "SELECT * FROM jobs WHERE book_id = ? ORDER BY id DESC LIMIT 1",
            (book["id"],),
        ).fetchone()
        return dict(book), dict(job) if job else None
    finally:
        con.close()


def _mirror_state(translation_id: str) -> Dict[str, Any]:
    if not translation_id or not MIRROR_DB.exists():
        return {}
    con = sqlite3.connect(f"file:{MIRROR_DB.as_posix()}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        job = con.execute(
            "SELECT status, progress, updated_at, file_type FROM translation_jobs "
            "WHERE translation_id = ?",
            (translation_id,),
        ).fetchone()
        if not job:
            return {}
        progress = json.loads(job["progress"] or "{}")
        file_type = str(job["file_type"] or "").lower()
        stats = con.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                   MAX(completed_at) AS last_at
            FROM checkpoint_chunks
            WHERE translation_id = ?
            """,
            (translation_id,),
        ).fetchone()
        recent = con.execute(
            "SELECT completed_at FROM checkpoint_chunks "
            "WHERE translation_id = ? AND status = 'completed' AND completed_at IS NOT NULL "
            "ORDER BY chunk_index DESC LIMIT 20",
            (translation_id,),
        ).fetchall()
        times = sorted(
            item for item in (_parse_time(row["completed_at"]) for row in recent)
            if item is not None
        )
        eta_seconds = None
        total_chunks = int(progress.get("total_chunks") or 0)
        # EPUB checkpoint rows are files; the global chunk count lives in the
        # progress JSON and is updated by the per-file xhtml state.
        completed = (
            int(progress.get("completed_chunks") or 0)
            if file_type == "epub"
            else int(stats["completed"] or 0)
        )
        completed_files = int(stats["completed"] or 0)
        last_at = _parse_time(stats["last_at"])
        updated_at = _parse_time(job["updated_at"])
        if updated_at and (last_at is None or updated_at > last_at):
            last_at = updated_at
        last_value = last_at.isoformat(timespec="seconds") if last_at else None
        # File-level rows are not a chunk timeline; the watchdog computes a
        # rolling chunk rate from its own samples and overrides this.
        if file_type != "epub" and len(times) >= 2:
            span = (times[-1] - times[0]).total_seconds()
            if span > 0 and completed < total_chunks:
                rate = (len(times) - 1) / span
                eta_seconds = int((total_chunks - completed) / rate)
        return {
            "status": job["status"],
            "file_type": file_type,
            "total_chunks": total_chunks,
            "checkpoint_count": completed,
            "completed_files": completed_files,
            "chunk_rows": int(stats["total"] or 0),
            "last_checkpoint_at": last_value,
            "updated_at": job["updated_at"],
            "eta_seconds": eta_seconds,
            "eta_human": _format_duration(eta_seconds) if eta_seconds else None,
        }
    finally:
        con.close()


def _mirror_sidecar() -> Dict[str, Any]:
    if not MIRROR_JSON.exists():
        return {}
    try:
        data = json.loads(MIRROR_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _container_output_name(book: Dict[str, Any]) -> str:
    return f"{book.get('title') or ''} (pt-BR).epub"


def _process_alive(book: Dict[str, Any]) -> Optional[bool]:
    code = (
        "from src.literary.kill_translation import find_pids; "
        "import json; print(json.dumps(find_pids(%r)))"
        % _container_output_name(book)
    )
    command = [
        "docker", "compose", "-f", str(COMPOSE_FILE),
        "exec", "-T", "app", "python", "-c", code,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    for line in reversed((completed.stdout or "").strip().splitlines()):
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            return bool(json.loads(line))
        except json.JSONDecodeError:
            continue
    return None


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


def _run_audit(book_id: int, translation_id: str) -> Dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "intra_run_audit.py"),
        "--book-id", str(book_id),
        "--translation-id", translation_id,
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
            timeout=300,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    payload = _parse_json(completed.stdout)
    if payload is None:
        return {
            "ok": False,
            "error": "no JSON from intra_run_audit",
            "returncode": completed.returncode,
            "stderr": (completed.stderr or "")[-500:],
        }
    payload["returncode"] = completed.returncode
    return payload


def _run_snapshot(label: str) -> Dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "db_snapshot.py"),
        "--label", label,
        "--keep-daily", "7",
        "--keep-labeled", "1",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    payload = _parse_json(completed.stdout)
    if payload is None:
        return {
            "ok": False,
            "error": "no JSON from db_snapshot",
            "returncode": completed.returncode,
            "stderr": (completed.stderr or "")[-500:],
        }
    payload["returncode"] = completed.returncode
    return payload


def _live_health() -> Dict[str, Any]:
    command = [
        "docker", "compose", "-f", str(COMPOSE_FILE),
        "exec", "-T", "app", "python", "-m", "src.literary.cli",
        "queue", "db-health", "--json",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except Exception as exc:
        return {"error": str(exc)}
    if completed.returncode != 0:
        return {"error": (completed.stderr or completed.stdout or "").strip()[-500:]}
    raw = (completed.stdout or "").strip()
    text = raw[raw.find("{"):] if "{" in raw else raw
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {"error": "invalid db-health JSON"}


def _queue_integrity() -> str:
    if not QUEUE_DB.exists():
        return "missing"
    con = sqlite3.connect(f"file:{QUEUE_DB.as_posix()}?mode=ro", uri=True, timeout=10)
    try:
        row = con.execute("PRAGMA quick_check").fetchone()
        return str(row[0] if row else "unknown")
    finally:
        con.close()


def _terminate(book: Dict[str, Any]) -> Dict[str, Any]:
    command = [
        "docker", "compose", "-f", str(COMPOSE_FILE),
        "exec", "-T", "app", "python", "-m", "src.literary.kill_translation",
        _container_output_name(book), "--signal", "TERM",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": completed.returncode == 0,
        "output": ((completed.stdout or "") + (completed.stderr or "")).strip()[-500:],
    }


def collect(stall_minutes: int, live_health: Dict[str, Any]) -> Dict[str, Any]:
    book, job = _active_book()
    payload: Dict[str, Any] = {
        "timestamp": _iso(),
        "active": bool(book),
        "stall_minutes": stall_minutes,
        "queue_integrity": _queue_integrity(),
        "live_db": live_health,
    }
    sidecar = _mirror_sidecar()
    generated = _parse_time(sidecar.get("generated_at"))
    mirror_age = (_now() - generated).total_seconds() if generated else None
    payload.update({
        "mirror_generated_at": sidecar.get("generated_at"),
        "mirror_age_seconds": round(mirror_age, 1) if mirror_age is not None else None,
        "mirror_integrity": sidecar.get("integrity"),
        "mirror_stale": mirror_age is not None and mirror_age > 90,
    })
    if not book:
        payload["state"] = "idle"
        return payload

    translation_id = str((job or {}).get("translation_id") or "")
    mirror = _mirror_state(translation_id)
    started = _parse_time((job or {}).get("created_at"))
    last = _parse_time(mirror.get("last_checkpoint_at"))
    if last is None:
        last = _parse_time((job or {}).get("updated_at"))
    age = (_now() - last).total_seconds() if last else None
    process_alive = _process_alive(book)
    stalled = bool(
        age is not None
        and age > stall_minutes * 60
        and process_alive is not False
    )
    payload.update({
        "book_id": book.get("id"),
        "title": book.get("title"),
        "state": book.get("status"),
        "translation_id": translation_id,
        "job_id": (job or {}).get("id"),
        "job_state": (job or {}).get("state"),
        "started_at": (job or {}).get("created_at"),
        "checkpoint_count": mirror.get("checkpoint_count"),
        "chunk_rows": mirror.get("chunk_rows"),
        "total_chunks": mirror.get("total_chunks"),
        "last_checkpoint_at": mirror.get("last_checkpoint_at"),
        "last_checkpoint_age_seconds": round(age, 1) if age is not None else None,
        "process_alive": process_alive,
        "stalled": stalled,
        "eta_seconds": mirror.get("eta_seconds"),
        "eta_human": mirror.get("eta_human"),
    })
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--stall-minutes", type=int, default=10)
    parser.add_argument("--audit-every", type=int, default=100)
    parser.add_argument("--no-audit", action="store_true")
    parser.add_argument("--audit-block", action="store_true")
    parser.add_argument("--snapshot-every-hours", type=float, default=6.0)
    parser.add_argument("--no-snapshots", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--terminate", action="store_true")
    args = parser.parse_args()

    existing: Dict[str, Any] = {}
    try:
        existing = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = {}
    live_health: Dict[str, Any] = {}
    live_checked = 0.0
    rate_history: list[tuple[float, int]] = []
    rate_key = ""
    last_audit: Dict[str, Any] = existing.get("last_audit") or {}
    audit_key = str(existing.get("audit_key") or "")
    last_audit_count = int(
        existing.get("audit_checkpoint_count")
        or (last_audit.get("checkpoint_count") if isinstance(last_audit, dict) else 0)
        or 0
    )
    last_snapshot: Dict[str, Any] = existing.get("last_snapshot") or {}
    next_snapshot = time.time() + max(0.1, args.snapshot_every_hours) * 3600
    try:
        next_snapshot = datetime.fromisoformat(
            str(existing.get("next_snapshot_at"))
        ).timestamp()
    except (ValueError, TypeError):
        pass
    while True:
        now = time.time()
        if now - live_checked > 300:
            live_health = _live_health()
            live_checked = now
        payload = collect(args.stall_minutes, live_health)
        if payload.get("active") and payload.get("checkpoint_count") is not None:
            key = f"{payload.get('book_id')}:{payload.get('translation_id')}"
            if key != rate_key:
                rate_history = []
                rate_key = key
            rate_history.append((now, int(payload["checkpoint_count"])))
            cutoff = now - 600
            rate_history = [item for item in rate_history if item[0] >= cutoff]
            if len(rate_history) >= 2:
                first_t, first_count = rate_history[0]
                last_t, last_count = rate_history[-1]
                span = last_t - first_t
                delta = last_count - first_count
                total = int(payload.get("total_chunks") or 0)
                if span >= 60 and delta > 0 and total > last_count:
                    eta_seconds = int((total - last_count) * span / delta)
                    payload["eta_seconds"] = eta_seconds
                    payload["eta_human"] = _format_duration(eta_seconds)
        if not args.no_audit and payload.get("active"):
            count = int(payload.get("checkpoint_count") or 0)
            key = f"{payload.get('book_id')}:{payload.get('translation_id')}"
            if key != audit_key:
                audit_key = key
                last_audit_count = 0
            if count > 0 and count >= last_audit_count + max(1, args.audit_every):
                result = _run_audit(
                    int(payload.get("book_id") or 0),
                    str(payload.get("translation_id") or ""),
                )
                last_audit_count = count
                last_audit = {
                    "timestamp": _iso(),
                    "passed": bool(result.get("passed")),
                    "report": result.get("report"),
                    "reasons": result.get("reasons") or [],
                    "metrics": result.get("metrics"),
                    "glossary_hash": result.get("glossary_hash"),
                    "checkpoint_count": count,
                }
                payload["last_audit"] = last_audit
                payload["audit_checkpoint_count"] = count
                if args.audit_block and result.get("passed") is False:
                    payload["audit_blocked"] = True
        if last_audit_count:
            payload["audit_checkpoint_count"] = last_audit_count
        if last_audit:
            payload["last_audit"] = last_audit
        payload["audit_key"] = audit_key
        if not args.no_snapshots and now >= next_snapshot:
            label = re.sub(
                r"[^a-z0-9]+", "-",
                str(payload.get("title") or "").strip().lower(),
            ).strip("-")
            result = _run_snapshot(label)
            last_snapshot = {
                "timestamp": _iso(),
                "ok": bool(result.get("ok")),
                "snapshots": result.get("snapshots") or [],
            }
            payload["last_snapshot"] = last_snapshot
            next_snapshot = time.time() + max(0.1, args.snapshot_every_hours) * 3600
        if last_snapshot:
            payload["last_snapshot"] = last_snapshot
        payload["next_snapshot_at"] = datetime.fromtimestamp(
            next_snapshot, timezone.utc
        ).isoformat(timespec="seconds")
        if args.terminate and payload.get("stalled") and payload.get("process_alive"):
            book = {"id": payload.get("book_id"), "title": payload.get("title")}
            payload["terminated"] = _terminate(book)
        _write_health(payload)
        if args.once:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if not payload.get("stalled") or not args.terminate else 1
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    sys.exit(main())
