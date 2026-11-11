"""Concurrency baseline for the literary queue API.

Reproduces the production-shaped failure mode on a scratch database:

- one writer process simulates the translation runner (short ``BEGIN
  IMMEDIATE`` commits, or a long held transaction for the timeout probe);
- the real Flask blueprint is served over HTTP with the real ``QueueStore``;
- 100 approve/retry/add/move/remove calls are fired concurrently;
- the run records ``database is locked``, 30 s timeouts, HTTP 5xx and the
  editorial-state inconsistencies left behind.

Nothing here opens the live ``data/literary_queue.db``. The scratch DB lives in
``data/tmp/concurrency-baseline-<stamp>/`` which is also visible to the app
container as ``/app/data/tmp/concurrency-baseline-<stamp>/``. That lets the
baseline run the writer inside the container and exercise the same 9p bind
mount the production runner uses.

Run from the repository root::

    python tests/standalone/concurrency_baseline.py

The report is written to the work dir as ``report.json``, ``report.md``,
``ops.jsonl`` and ``server.log``.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sqlite3
import statistics
import subprocess
import sys
import importlib.util
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from src.literary import queue_intents  # noqa: E402


def _load_blueprint_module():
    """Load the real route module without importing the whole API package.

    ``src/api/__init__.py`` imports every blueprint of the upstream app, which
    pulls requests/litellm and other dependencies that this baseline does not
    need. The file executed here is the same one the app serves.
    """
    path = ROOT / "src" / "api" / "blueprints" / "literary_queue_routes.py"
    spec = importlib.util.spec_from_file_location("baseline_literary_queue_routes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_blueprint_module = _load_blueprint_module()
create_literary_queue_blueprint = _blueprint_module.create_literary_queue_blueprint

COMPOSE = ROOT / "docker-compose.dev.yml"
WRITER = ROOT / "tests" / "standalone" / "concurrency_writer.py"
WRITER_CONTAINER = "/app/tests/standalone/concurrency_writer.py"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _container_path(path: Path) -> str:
    return "/app/" + path.relative_to(ROOT).as_posix()


def _new_db(path: Path) -> None:
    from src.literary.queue import QueueStore

    QueueStore(str(path)).close()


def _insert_book(
    conn: sqlite3.Connection,
    *,
    calibre_id: int,
    title: str,
    status: str,
    priority: int,
    job_state: str,
    current: int = 0,
    total: int = 100,
    translation_id: str = "",
) -> int:
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO books (
            calibre_id, source_path, title, author, series, series_index,
            source_language, target_language, word_count, status, priority,
            glossary_scope, style_scope, model, provider, estimated_cost,
            actual_cost, source_hash, config_hash, reviewed_at, created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', 'mock', 'ollama',
                  0, 0, ?, ?, '', ?, ?)
        """,
        (
            calibre_id,
            f"data/tmp/fake-{calibre_id}.epub",
            title,
            "Concurrency Author",
            "Concurrency Series",
            1.0,
            "en",
            "pt-BR",
            1000 + calibre_id,
            status,
            priority,
            f"src-{calibre_id}",
            f"cfg-{calibre_id}",
            now,
            now,
        ),
    )
    book_id = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO jobs (
            book_id, state, translation_id, current_chapter, total_chapters,
            checkpoint_json, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, '{}', '', ?, ?)
        """,
        (book_id, job_state, translation_id, current, total, now, now),
    )
    return book_id


def _seed(db: Path, *, shallow: bool = False) -> Dict[str, Any]:
    _new_db(db)
    conn = sqlite3.connect(db)
    try:
        seed: Dict[str, Any] = {}
        seed["translating"] = _insert_book(
            conn,
            calibre_id=1,
            title="Live Translation",
            status="translating",
            priority=1_000_000,
            job_state="translating",
            current=10,
            total=100,
            translation_id="tr-live",
        )
        needs = 2 if shallow else 20
        pending = 1 if shallow else 20
        paused = 1 if shallow else 10
        failed = 1 if shallow else 10
        seed["needs_review"] = [
            _insert_book(
                conn,
                calibre_id=100 + index,
                title=f"Needs Review {index}",
                status="needs_review",
                priority=900_000 - index,
                job_state="needs_review",
            )
            for index in range(needs)
        ]
        seed["pending"] = [
            _insert_book(
                conn,
                calibre_id=200 + index,
                title=f"Pending {index}",
                status="pending",
                priority=100 - index,
                job_state="pending",
            )
            for index in range(pending)
        ]
        seed["paused"] = [
            _insert_book(
                conn,
                calibre_id=300 + index,
                title=f"Paused {index}",
                status="paused",
                priority=800_000 - index,
                job_state="paused",
            )
            for index in range(paused)
        ]
        seed["failed"] = [
            _insert_book(
                conn,
                calibre_id=400 + index,
                title=f"Failed {index}",
                status="failed",
                priority=700_000 - index,
                job_state="failed",
            )
            for index in range(failed)
        ]
        conn.execute(
            "INSERT INTO events (book_id, job_id, level, message, created_at) "
            "VALUES (?, NULL, 'info', 'baseline seed', ?)",
            (seed["translating"], _now()),
        )
        conn.commit()
        return seed
    finally:
        conn.close()


def _inventory(path: Path, start: int, count: int) -> Path:
    rows = []
    for calibre_id in range(start, start + count):
        epub = path.parent / "fake-epubs" / f"{calibre_id}.epub"
        epub.parent.mkdir(parents=True, exist_ok=True)
        epub.write_bytes(b"fake epub")
        rows.append(
            {
                "calibre_id": calibre_id,
                "title": f"Concurrency Add {calibre_id}",
                "author": "Concurrency Author",
                "series": "Concurrency Series",
                "series_index": 1.0,
                "languages": ["en"],
                "calibre_path": f"Concurrency Author/Concurrency Add {calibre_id} ({calibre_id})",
                "epub_path": str(epub),
                "word_count": 1000 + calibre_id,
            }
        )
    path.write_text(json.dumps({"books": rows}, ensure_ascii=False), encoding="utf-8")
    return path


def _ops(seed: Dict[str, Any]) -> List[Dict[str, Any]]:
    needs = seed["needs_review"]
    pending = seed["pending"]
    paused = seed["paused"]
    failed = seed["failed"]
    ops: List[Dict[str, Any]] = []

    # 20 approves across every needs_review book.
    for book_id in needs:
        ops.append({"kind": "approve", "book_id": book_id})
    # 15 retries: all paused + first five failed.
    for book_id in paused:
        ops.append({"kind": "retry", "book_id": book_id})
    for book_id in failed[:5]:
        ops.append({"kind": "retry", "book_id": book_id})
    # 20 moves, alternating direction.
    for index, book_id in enumerate(pending):
        ops.append(
            {"kind": "move", "book_id": book_id, "direction": "up" if index % 2 == 0 else "down"}
        )
    # 10 removes: last five failed + last five needs_review (race with approve).
    for book_id in failed[-5:] + needs[-5:]:
        ops.append({"kind": "remove", "book_id": book_id})
    # 15 adds.
    for calibre_id in range(1000, 1015):
        ops.append({"kind": "add", "calibre_id": calibre_id})
    # 5 retries racing the approve on the first five needs_review books.
    for book_id in needs[:5]:
        ops.append({"kind": "retry", "book_id": book_id})
    # 5 approves racing a remove on the next five needs_review books.
    for book_id in needs[10:15]:
        ops.append({"kind": "approve", "book_id": book_id})
    # 5 removes racing the move on the first five pending books.
    for book_id in pending[:5]:
        ops.append({"kind": "remove", "book_id": book_id})
    # 5 more moves on the next five pending books.
    for book_id in pending[5:10]:
        ops.append({"kind": "move", "book_id": book_id, "direction": "up"})

    random.Random(42).shuffle(ops)
    assert len(ops) == 100, len(ops)
    return ops


def _probe_ops(seed: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"kind": "approve", "book_id": seed["needs_review"][0]},
        {"kind": "retry", "book_id": seed["paused"][0]},
        {"kind": "move", "book_id": seed["pending"][0], "direction": "up"},
        {"kind": "remove", "book_id": seed["failed"][0]},
        {"kind": "add", "calibre_id": 2000},
    ]


def _call(base: str, op: Dict[str, Any], timeout: float = 70.0) -> Dict[str, Any]:
    kind = op["kind"]
    if kind == "add":
        url = f"{base}/api/literary/queue/books"
        method = "POST"
        payload: Optional[Dict[str, Any]] = {
            "calibre_ids": [op["calibre_id"]],
            "target_language": "pt-BR",
        }
    else:
        url = f"{base}/api/literary/queue/books/{op['book_id']}"
        if kind == "remove":
            method = "DELETE"
            payload = None
        elif kind == "move":
            url += "/move"
            method = "POST"
            payload = {"direction": op["direction"]}
        elif kind == "approve":
            url += "/approve"
            method = "POST"
            payload = {}
        elif kind == "retry":
            url += "/retry"
            method = "POST"
            payload = {}
        else:
            raise ValueError(kind)

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    status = 0
    body = ""
    error = ""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            body = response.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(4000).decode("utf-8", "replace")
    except Exception as exc:  # transport timeout, connection reset, ...
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    return {
        "kind": kind,
        "book_id": op.get("book_id"),
        "calibre_id": op.get("calibre_id"),
        "direction": op.get("direction"),
        "status": status,
        "elapsed_s": round(elapsed, 3),
        "error": error,
        "body": body[:600],
    }


def _classify(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    for item in results:
        body = (item.get("body") or "").lower()
        item["locked"] = "database is locked" in body or "database table is locked" in body
        # Any request that waited at least 29 s hit the 30 s sqlite busy timeout,
        # even when the final status is a generic 500 or a client-side timeout.
        item["timeout"] = item["elapsed_s"] >= 29.0
        item["server_error"] = 500 <= int(item["status"]) < 600
        item["transport"] = int(item["status"]) == 0
        item["ok"] = 200 <= int(item["status"]) < 300
        item["expected_conflict"] = int(item["status"]) == 409
        item["not_found"] = int(item["status"]) == 404
        item["malformed"] = "malformed" in body
        item["api_failure"] = bool(
            item["locked"]
            or item["timeout"]
            or item["server_error"]
            or item["transport"]
        )

    total = len(results)
    elapsed = [float(item["elapsed_s"]) for item in results] or [0.0]
    failures = sum(1 for item in results if item["api_failure"])
    return {
        "total": total,
        "ok": sum(1 for item in results if item["ok"]),
        "expected_conflict": sum(1 for item in results if item["expected_conflict"]),
        "not_found": sum(1 for item in results if item["not_found"]),
        "locked": sum(1 for item in results if item["locked"]),
        "malformed": sum(1 for item in results if item["malformed"]),
        "timeout": sum(1 for item in results if item["timeout"]),
        "server_error": sum(1 for item in results if item["server_error"]),
        "transport": sum(1 for item in results if item["transport"]),
        "api_failures": failures,
        "api_failure_rate": round(failures / total, 4) if total else 0.0,
        "lock_rate": round(sum(1 for item in results if item["locked"]) / total, 4)
        if total
        else 0.0,
        "timeout_rate": round(sum(1 for item in results if item["timeout"]) / total, 4)
        if total
        else 0.0,
        "max_elapsed_s": round(max(elapsed), 3),
        "p50_elapsed_s": round(statistics.median(elapsed), 3),
        "p95_elapsed_s": round(
            sorted(elapsed)[max(0, int(len(elapsed) * 0.95) - 1)], 3
        )
        if elapsed
        else 0.0,
    }


def _add_strict_metrics(
    summary: Dict[str, Any], results: List[Dict[str, Any]], ops: List[Dict[str, Any]]
) -> None:
    """Count 404s that no remove operation can explain.

    ``_book_meta`` swallows sqlite read errors and returns None, so a corrupt DB
    surfaces as "book not found". A 404 is only an expected race when another
    operation actually removed that same book.
    """
    remove_ids = {op.get("book_id") for op in ops if op.get("kind") == "remove"}
    unexplained = [
        item
        for item in results
        if int(item.get("status") or 0) == 404 and item.get("book_id") not in remove_ids
    ]
    summary["unexplained_404"] = len(unexplained)
    summary["api_failures_strict"] = summary["api_failures"] + len(unexplained)
    summary["api_failure_rate_strict"] = (
        round(summary["api_failures_strict"] / summary["total"], 4)
        if summary["total"]
        else 0.0
    )


def _state(db: Path, translating_id: int, initial_progress: int = 10) -> Dict[str, Any]:
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        foreign_keys = [
            dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()
        ]
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT b.id, b.title, b.status, b.reviewed_at,
                       j.id AS job_id, j.state AS job_state,
                       j.current_chapter, j.total_chapters
                FROM books b
                LEFT JOIN jobs j
                  ON j.id = (SELECT MAX(id) FROM jobs WHERE book_id = b.id)
                ORDER BY b.id
                """
            )
        ]
        dangling = int(
            conn.execute(
                "SELECT COUNT(*) FROM events e "
                "WHERE e.book_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM books b WHERE b.id = e.book_id)"
            ).fetchone()[0]
        )
    except sqlite3.Error as exc:
        return {
            "integrity": f"error: {exc}",
            "foreign_key_violations": [],
            "dangling_events": 0,
            "books": [],
            "translating_alive": False,
            "inconsistencies": [
                {
                    "kind": "state_read_error",
                    "book_id": translating_id,
                    "title": None,
                    "status": None,
                    "job_state": None,
                    "detail": f"could not read the queue state: {exc}",
                }
            ],
            "inconsistency_count": 1,
            "state_ok": False,
        }
    finally:
        if conn is not None:
            conn.close()

    inconsistencies: List[Dict[str, Any]] = []
    active = {"preparing", "translating", "reviewing", "validating"}

    def flag(kind: str, row: Dict[str, Any], detail: str) -> None:
        inconsistencies.append(
            {
                "kind": kind,
                "book_id": row.get("id"),
                "title": row.get("title"),
                "status": row.get("status"),
                "job_state": row.get("job_state"),
                "reviewed_at": row.get("reviewed_at"),
                "detail": detail,
            }
        )

    translating = None
    for row in rows:
        status = str(row.get("status") or "")
        job_state = str(row.get("job_state") or "")
        reviewed = bool(str(row.get("reviewed_at") or "").strip())
        if row["id"] == translating_id:
            translating = row
        if status == "completed" and not reviewed:
            flag("completed_without_review", row, "book completed but reviewed_at is empty")
        if status == "completed" and job_state != "completed":
            flag(
                "completed_without_completed_job",
                row,
                f"book completed but latest job is {job_state or 'missing'}",
            )
        if status == "needs_review" and job_state == "completed":
            flag(
                "needs_review_with_completed_job",
                row,
                "partial approval: job completed, book still needs_review",
            )
        if reviewed and status != "completed":
            flag(
                "reviewed_without_completed",
                row,
                f"reviewed_at set while book is {status}",
            )
        if status == "pending" and job_state in active:
            flag(
                "pending_with_active_job",
                row,
                f"book pending but latest job is {job_state}",
            )
        if status in active and job_state not in active:
            flag(
                "active_without_active_job",
                row,
                f"book {status} but latest job is {job_state or 'missing'}",
            )

    translating_alive = bool(
        translating
        and translating.get("status") == "translating"
        and translating.get("job_state") == "translating"
        and int(translating.get("current_chapter") or 0) > initial_progress
    )
    if not translating_alive:
        inconsistencies.append(
            {
                "kind": "translating_book_not_alive",
                "book_id": translating_id,
                "title": (translating or {}).get("title"),
                "status": (translating or {}).get("status"),
                "job_state": (translating or {}).get("job_state"),
                "detail": "the simulated live translation did not stay alive and progress",
            }
        )

    if dangling:
        inconsistencies.append(
            {
                "kind": "dangling_events",
                "book_id": None,
                "title": None,
                "status": None,
                "job_state": None,
                "detail": f"{dangling} event(s) reference a deleted book",
            }
        )

    return {
        "integrity": integrity,
        "foreign_key_violations": foreign_keys,
        "dangling_events": dangling,
        "books": rows,
        "translating_alive": translating_alive,
        "inconsistencies": inconsistencies,
        "inconsistency_count": len(inconsistencies),
        "state_ok": integrity.lower() == "ok" and not foreign_keys and not inconsistencies,
    }


def _wait_marker(path: Path, marker: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if marker in path.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


def _start_writer(
    *,
    db: Path,
    log: Path,
    mode: str,
    container: bool,
    seconds: float = 60.0,
    hold_seconds: float = 35.0,
    stop_file: Optional[Path] = None,
    process_log: Path,
) -> subprocess.Popen:
    if container:
        command = [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "exec",
            "-T",
            "app",
            "python",
            WRITER_CONTAINER,
            "--db",
            _container_path(db),
            "--log",
            _container_path(log),
            "--mode",
            mode,
        ]
    else:
        command = [
            sys.executable,
            str(WRITER),
            "--db",
            str(db),
            "--log",
            str(log),
            "--mode",
            mode,
        ]
    if mode == "hold":
        command.extend(["--hold-seconds", str(hold_seconds)])
    else:
        command.extend(["--seconds", str(seconds), "--interval", "0.01"])
        if stop_file is not None:
            command.extend(
                [
                    "--stop-file",
                    _container_path(stop_file) if container else str(stop_file),
                ]
            )
    handle = process_log.open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process._baseline_log_handle = handle  # type: ignore[attr-defined]
    return process


def _stop_writer(process: subprocess.Popen, stop_file: Optional[Path] = None) -> None:
    if stop_file is not None:
        stop_file.write_text("stop\n", encoding="utf-8")
    if process.poll() is None:
        try:
            # The writer may be inside a 30 s BEGIN IMMEDIATE wait; give it
            # enough room to acquire the lock, see the stop file and commit.
            process.wait(timeout=40)
        except subprocess.TimeoutExpired:
            process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    handle = getattr(process, "_baseline_log_handle", None)
    if handle is not None:
        handle.close()


def _start_applier(db: Path, log: Path) -> subprocess.Popen:
    """Host runner stand-in: applies queue intents, the only writer of ``db``.

    It runs on the host like ``queue run-all`` and the agent do in production.
    """
    stop = db.with_name(f"{db.stem}.applier.stop")
    stop.unlink(missing_ok=True)
    handle = log.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "src.literary.queue_intents",
            "--db",
            str(db),
            "--interval",
            "0.2",
            "--stop-file",
            str(stop),
        ],
        cwd=ROOT,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process._applier_stop = stop  # type: ignore[attr-defined]
    process._applier_log_handle = handle  # type: ignore[attr-defined]
    return process


def _settle_intents(process: subprocess.Popen, db: Path, timeout: float = 60.0) -> Dict[str, Any]:
    """Wait until every intent is applied, then stop the applier and count."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if queue_intents.pending_summary(db)["pending"] == 0:
            break
        time.sleep(0.2)
    process._applier_stop.write_text("stop\n", encoding="utf-8")  # type: ignore[attr-defined]
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    process._applier_log_handle.close()  # type: ignore[attr-defined]
    return _intent_stats(db)


def _intent_stats(db: Path) -> Dict[str, Any]:
    """Outcome of every intent in the scratch database (read-only)."""
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT kind, applied_at, error, error_status FROM queue_intents"
        ).fetchall()
    except sqlite3.Error as exc:
        return {"error": f"could not read queue_intents: {exc}"}
    finally:
        conn.close()
    refusals: Dict[str, int] = {}
    for _kind, applied_at, error, status in rows:
        if applied_at and error and int(status or 0) < 500:
            refusals[f"{status} {error}"] = refusals.get(f"{status} {error}", 0) + 1
    return {
        "total": len(rows),
        "applied": sum(1 for row in rows if row[1] and not row[2]),
        "refused": sum(1 for row in rows if row[1] and row[2] and int(row[3] or 0) < 500),
        "failed": sum(1 for row in rows if row[1] and int(row[3] or 0) >= 500),
        "pending": sum(1 for row in rows if not row[1]),
        "refusals": refusals,
    }


def _count_lock_lines(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return 0
    return text.count("database is locked") + text.count("database table is locked")


def _writer_stats(path: Path) -> Dict[str, Any]:
    """Read the last JSON summary printed by the writer process."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "mode" in payload:
            return payload
    return {}


def _wait_writer(process: subprocess.Popen, timeout: float) -> None:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    handle = getattr(process, "_baseline_log_handle", None)
    if handle is not None:
        handle.close()


def _configure_app(db: Path, inventory: Path, work: Path, server_log: Path) -> Flask:
    os.environ["LITERARY_QUEUE_DB"] = str(db)
    os.environ["LITERARY_INVENTORY"] = str(inventory)
    os.environ["LITERARY_OUTPUT_DIR"] = str(work / "outputs")
    os.environ["LITERARY_RUN_DIR"] = str(work / "run")
    os.environ["LITERARY_PILOT_DIR"] = str(work / "pilot")
    os.environ["LITERARY_KINDLE_DIR"] = str(work / "kindle")
    os.environ["JOBS_DB_PATH"] = str(work / "jobs.db")
    os.environ["QUEUE_HEALTH_PATH"] = str(work / "health.json")

    app = Flask(__name__)
    app.register_blueprint(create_literary_queue_blueprint())

    # Harness instrumentation only: turn unhandled sqlite errors into JSON 500s
    # so the request log records "database is locked" or "malformed" instead of
    # Flask's generic HTML error page. The database behaviour is unchanged.
    @app.errorhandler(sqlite3.DatabaseError)
    def _sqlite_error(exc: sqlite3.DatabaseError):  # type: ignore[no-untyped-def]
        return jsonify({"status": "error", "error": str(exc)}), 500

    handler = logging.FileHandler(server_log, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.addHandler(handler)
    werkzeug_logger.setLevel(logging.INFO)
    return app


def _run_ops(base: str, ops: List[Dict[str, Any]], workers: int) -> List[Dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_call, base, op) for op in ops]
        return [future.result() for future in futures]


def _write_report(work: Path, report: Dict[str, Any], ops: List[Dict[str, Any]]) -> None:
    (work / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (work / "ops.jsonl").open("w", encoding="utf-8") as handle:
        for item in ops:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    main = report["main"]["summary"]
    state = report["main"]["state"]
    lines = [
        "# Concurrency baseline — literary queue API",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Work dir: `{work}`",
        f"- DB: `{report['main']['db']}`",
        f"- Writer: {report['main']['writer']}",
        f"- Ops: {main['total']}",
        "",
        "## API result",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| 2xx | {main['ok']} |",
        f"| 409 expected conflict | {main['expected_conflict']} |",
        f"| 404 race not found | {main['not_found']} |",
        f"| 500 | {main['server_error']} |",
        f"| database is locked | {main['locked']} |",
        f"| lock messages in server.log | {main.get('lock_messages_in_server_log', 0)} |",
        f"| timeout >= 29 s | {main['timeout']} |",
        f"| transport error | {main['transport']} |",
        f"| API failure rate | {main['api_failure_rate']:.2%} |",
        f"| max elapsed | {main['max_elapsed_s']} s |",
        f"| p95 elapsed | {main['p95_elapsed_s']} s |",
        "",
    ]
    intents = report["main"].get("intents") or {}
    lines.extend(
        [
            "## Queue intents",
            "",
            f"- Accepted with 202 (runner behind): {report['main'].get('accepted_202', 0)}",
            f"- Applied: {intents.get('applied', 0)}, refused: {intents.get('refused', 0)}, "
            f"failed: {intents.get('failed', 0)}, pending after settle: {intents.get('pending', 0)}",
        ]
    )
    for reason, count in sorted((intents.get("refusals") or {}).items()):
        lines.append(f"- refused {count}x: `{reason}`")
    lines.append("")
    writer_stats = report["main"].get("writer_stats") or {}
    if writer_stats:
        lines.extend(
            [
                "## Writer",
                "",
                f"- Iterations: {writer_stats.get('iterations', 0)}",
                f"- Lock errors: {writer_stats.get('lock_errors', 0)}",
                f"- Disk I/O errors: {writer_stats.get('io_errors', 0)}",
                f"- Other errors: {writer_stats.get('other_errors', 0)}",
                "",
            ]
        )
    lines.extend(
        [
            "## State",
            "",
            f"- Integrity: `{state['integrity']}`",
            f"- FK violations: {len(state['foreign_key_violations'])}",
            f"- Dangling events: {state['dangling_events']}",
            f"- Translating book alive: {state['translating_alive']}",
            f"- Inconsistencies: {state['inconsistency_count']}",
            "",
        ]
    )
    if state["inconsistencies"]:
        lines.extend(["| Kind | Book | Status | Job | Detail |", "| --- | --- | --- | --- | --- |"])
        for item in state["inconsistencies"][:30]:
            lines.append(
                f"| {item['kind']} | {item.get('book_id')} | {item.get('status')} | "
                f"{item.get('job_state')} | {item.get('detail')} |"
            )
        lines.append("")

    lines.extend(["## Probes", ""])
    for name, probe in report.get("probes", {}).items():
        summary = probe.get("summary") or {}
        lines.append(
            f"- **{name}**: {summary.get('api_failures', 0)}/{summary.get('total', 0)} "
            f"API failures, {summary.get('successful_writes_during_hold', 0)} write(s) "
            f"succeeded while the hold was open, max {summary.get('max_elapsed_s', 0)} s, "
            f"integrity `{(probe.get('state') or {}).get('integrity')}`"
        )
    lines.append("")
    lines.append("## Files")
    lines.extend(
        [
            f"- `report.json`",
            f"- `ops.jsonl` — every request and response",
            f"- `server.log` — Flask/Werkzeug exceptions",
            f"- `writer-main.log`, `writer-hold-host.log`, `writer-hold-9p.log`",
        ]
    )
    (work / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--ops", type=int, default=100)
    parser.add_argument("--skip-9p", action="store_true")
    parser.add_argument("--skip-host-hold", action="store_true")
    parser.add_argument(
        "--writer",
        choices=["host", "container"],
        default="host",
        help=(
            "side of the bind mount the simulated runner writes from. 'host' matches "
            "production after the single writer; 'container' reproduces the 5.3 run"
        ),
    )
    args = parser.parse_args()

    work = ROOT / "data" / "tmp" / f"concurrency-baseline-{_stamp()}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"work dir: {work}")

    main_db = work / "queue.db"
    seed = _seed(main_db)
    inventory = _inventory(work / "inventory.json", 1000, 30)
    ops = _ops(seed)
    if args.ops != 100:
        ops = ops[: args.ops]

    server_log = work / "server.log"
    app = _configure_app(main_db, inventory, work, server_log)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    base = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"api: {base}")

    report: Dict[str, Any] = {
        "schema": "literary.concurrency-baseline",
        "schema_version": "1.0",
        "generated_at": _now(),
        "work_dir": str(work),
        "main": {},
        "probes": {},
    }

    writer_log = work / "writer-main.log"
    writer_process_log = work / "writer-main.process.log"
    writer_stop = work / "writer-main.stop"
    locks_before = _count_lock_lines(server_log)
    applier = _start_applier(main_db, work / "applier-main.log")
    writer = _start_writer(
        db=main_db,
        log=writer_log,
        mode="short",
        container=(args.writer == "container"),
        seconds=60,
        stop_file=writer_stop,
        process_log=writer_process_log,
    )
    if not _wait_marker(writer_log, "writer_start", timeout=20):
        _stop_writer(writer, writer_stop)
        _settle_intents(applier, main_db)
        raise SystemExit(f"{args.writer} writer did not start; see {writer_process_log}")

    print(f"firing {len(ops)} operations with {args.workers} workers")
    results = _run_ops(base, ops, args.workers)
    _stop_writer(writer, writer_stop)
    main_intents = _settle_intents(applier, main_db)
    time.sleep(1.0)
    main_state = _state(main_db, seed["translating"])
    main_summary = _classify(results)
    _add_strict_metrics(main_summary, results, ops)
    main_summary["lock_messages_in_server_log"] = (
        _count_lock_lines(server_log) - locks_before
    )
    report["main"] = {
        "db": str(main_db),
        "writer": (
            "container (9p bind mount)"
            if args.writer == "container"
            else "host (NTFS, same side as the runner)"
        ),
        "summary": main_summary,
        "writer_stats": _writer_stats(writer_process_log),
        "state": main_state,
        "intents": main_intents,
        "accepted_202": sum(1 for item in results if item["status"] == 202),
    }
    print(json.dumps(report["main"]["summary"], ensure_ascii=False, indent=2))
    print(
        f"state: integrity={main_state['integrity']} "
        f"inconsistencies={main_state['inconsistency_count']}"
    )

    # Timeout probe 1: a host process holds a write transaction for 35 s.
    if not args.skip_host_hold:
        probe_db = work / "queue-hold-host.db"
        probe_seed = _seed(probe_db, shallow=True)
        probe_inventory = _inventory(work / "inventory-probe.json", 2000, 10)
        os.environ["LITERARY_QUEUE_DB"] = str(probe_db)
        os.environ["LITERARY_INVENTORY"] = str(probe_inventory)
        hold_log = work / "writer-hold-host.log"
        hold = _start_writer(
            db=probe_db,
            log=hold_log,
            mode="hold",
            container=False,
            hold_seconds=35,
            process_log=work / "writer-hold-host.process.log",
        )
        if not _wait_marker(hold_log, "hold_start", timeout=20):
            _stop_writer(hold)
            report["probes"]["host_hold"] = {"error": "hold writer did not start"}
        else:
            print("host hold active; firing 5 probe operations")
            host_applier = _start_applier(probe_db, work / "applier-hold-host.log")
            locks_before = _count_lock_lines(server_log)
            probe_ops = _probe_ops(probe_seed)
            probe_results = _run_ops(base, probe_ops, 5)
            _stop_writer(hold)
            host_intents = _settle_intents(host_applier, probe_db)
            probe_summary = _classify(probe_results)
            _add_strict_metrics(probe_summary, probe_results, probe_ops)
            probe_summary["lock_messages_in_server_log"] = (
                _count_lock_lines(server_log) - locks_before
            )
            probe_summary["successful_writes_during_hold"] = probe_summary["ok"]
            probe_summary["accepted_202"] = sum(
                1 for item in probe_results if item["status"] == 202
            )
            report["probes"]["host_hold"] = {
                "db": str(probe_db),
                "hold_seconds": 35,
                "summary": probe_summary,
                "writer_stats": _writer_stats(work / "writer-hold-host.process.log"),
                "state": _state(probe_db, probe_seed["translating"]),
                "intents": host_intents,
                "ops": probe_results,
            }
            print(json.dumps(report["probes"]["host_hold"]["summary"], ensure_ascii=False))

    # Timeout probe 2: the same hold, but from inside the app container. If the
    # 9p mount does not propagate POSIX locks to the Windows host, these calls
    # will not wait for the hold.
    if not args.skip_9p:
        probe_db = work / "queue-hold-9p.db"
        probe_seed = _seed(probe_db, shallow=True)
        probe_inventory = _inventory(work / "inventory-probe-9p.json", 3000, 10)
        os.environ["LITERARY_QUEUE_DB"] = str(probe_db)
        os.environ["LITERARY_INVENTORY"] = str(probe_inventory)
        hold_log = work / "writer-hold-9p.log"
        hold = _start_writer(
            db=probe_db,
            log=hold_log,
            mode="hold",
            container=True,
            hold_seconds=35,
            process_log=work / "writer-hold-9p.process.log",
        )
        if not _wait_marker(hold_log, "hold_start", timeout=20):
            _stop_writer(hold)
            report["probes"]["container_hold"] = {
                "error": "container hold writer did not start",
                "process_log": str(work / "writer-hold-9p.process.log"),
            }
        else:
            print("container hold active; firing 5 probe operations")
            container_applier = _start_applier(probe_db, work / "applier-hold-9p.log")
            locks_before = _count_lock_lines(server_log)
            probe_ops = _probe_ops(probe_seed)
            probe_results = _run_ops(base, probe_ops, 5)
            _stop_writer(hold)
            container_intents = _settle_intents(container_applier, probe_db)
            probe_summary = _classify(probe_results)
            _add_strict_metrics(probe_summary, probe_results, probe_ops)
            probe_summary["lock_messages_in_server_log"] = (
                _count_lock_lines(server_log) - locks_before
            )
            probe_summary["successful_writes_during_hold"] = probe_summary["ok"]
            probe_summary["accepted_202"] = sum(
                1 for item in probe_results if item["status"] == 202
            )
            report["probes"]["container_hold"] = {
                "db": str(probe_db),
                "hold_seconds": 35,
                "summary": probe_summary,
                "writer_stats": _writer_stats(work / "writer-hold-9p.process.log"),
                "state": _state(probe_db, probe_seed["translating"]),
                "intents": container_intents,
                "ops": probe_results,
            }
            print(json.dumps(report["probes"]["container_hold"]["summary"], ensure_ascii=False))

    server.shutdown()
    thread.join(timeout=10)
    report["finished_at"] = _now()
    _write_report(work, report, results)
    print((work / "report.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
