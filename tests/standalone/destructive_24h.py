"""Destructive reliability runner for the literary queue.

Two modes:

- ``short`` (safe now): corrupt-DB recovery on copies, a real kill/resume of a
  container translation against a scratch jobs DB and the mock model, a
  duplicate-output probe, a pause-control transition test, and an optional app
  restart health check. It never touches the live queue DB or the live jobs DB.
- ``window`` (requires a maintenance window): the same phases against a
  dedicated app instance with a scratch queue DB, plus a real pause/resume, an
  app restart mid-translation, and a 24 h soak. Refuses to run without
  ``--confirm-window`` and the dedicated compose file.

Run:

    python tests/standalone/destructive_24h.py --mode short --app-restart
    python tests/standalone/destructive_24h.py --mode window --confirm-window \
        --compose docker-compose.destructive.yml

The report is written to ``data/tmp/destructive-24h-<stamp>/report.{json,md}``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.literary.models import BookRecord  # noqa: E402
from src.literary.queue import QueueStore  # noqa: E402
from src.literary.queue_control import (  # noqa: E402
    honor_pause_now,
    pause_now_requested,
    set_pause_now,
)

COMPOSE = ROOT / "docker-compose.dev.yml"
MOCK = ROOT / "tests" / "standalone" / "mock_ollama.py"
BUILD_EPUB = ROOT / "tests" / "standalone" / "build_destructive_epub.py"
RECOVERY = ROOT / "tests" / "standalone" / "destructive_recovery.py"
MOCK_PORT = 11555


ACTIVE_STATES = {"preparing", "translating", "reviewing", "validating"}
LIVE_DB = ROOT / "data" / "literary_queue.db"
LIVE_RUNNER = ROOT / "data" / "literary_queue.runner.json"
LIVE_CONTAINER = "translatebook-literary-dev"
DEDICATED_COMPOSE = ROOT / "docker-compose.destructive.yml"
EXIT_NOT_READY = 3
CRITERIA_NAMES = ("no_state_without_checkpoint", "no_job_stuck_running", "no_duplicate_suffix")


def live_activity(active_books: List[str], runner_running: bool, container_top: str) -> List[str]:
    """Reasons the live stack is busy. An empty list means it is idle."""
    reasons = [f"book in an active state: {title}" for title in active_books]
    if runner_running:
        reasons.append("runner.json says a run is in progress")
    if "translate.py" in container_top:
        reasons.append(f"a translate.py process runs in {LIVE_CONTAINER}")
    return reasons


def _read_live_state() -> Dict[str, Any]:
    active_books: List[str] = []
    if LIVE_DB.exists():
        conn = sqlite3.connect(f"file:{LIVE_DB.resolve().as_posix()}?mode=ro", uri=True)
        try:
            placeholders = ",".join("?" for _ in ACTIVE_STATES)
            rows = conn.execute(
                f"SELECT title FROM books WHERE status IN ({placeholders})", tuple(ACTIVE_STATES)
            ).fetchall()
            active_books = [str(row[0]) for row in rows]
        finally:
            conn.close()
    runner_running = False
    if LIVE_RUNNER.exists():
        try:
            runner_running = bool(json.loads(LIVE_RUNNER.read_text(encoding="utf-8")).get("running"))
        except (OSError, ValueError):
            runner_running = True  # unreadable means busy, never idle
    container_top, container_error = "", False
    try:
        completed = subprocess.run(
            ["docker", "top", LIVE_CONTAINER], capture_output=True, text=True, timeout=30
        )
        container_top = completed.stdout or ""
        container_error = completed.returncode != 0
    except (OSError, subprocess.SubprocessError):
        container_error = True
    return {
        "active_books": active_books,
        "runner_running": runner_running,
        "container_top": container_top,
        "container_error": container_error,
    }


def preflight(mode: str, compose: Optional[Path]) -> Dict[str, Any]:
    """Read-only check. It never starts, stops or writes to the live stack."""
    state = _read_live_state()
    reasons = live_activity(state["active_books"], state["runner_running"], state["container_top"])
    if state["container_error"]:
        reasons.append(f"cannot inspect {LIVE_CONTAINER} (docker top failed)")
    if mode == "window" and (compose is None or not compose.exists()):
        reasons.append(f"dedicated compose file missing: {DEDICATED_COMPOSE.name}")
    return {"mode": mode, "ready": not reasons, "reasons": reasons, "checked_at": _now()}


DUPLICATE_SUFFIX = re.compile(r" \(\d+\)\.epub$")


def _checkpoint(raw_json: Any) -> Dict[str, Any]:
    try:
        return json.loads(raw_json) if raw_json else {}
    except (TypeError, ValueError):
        return {}


def evaluate_criteria(db_path: Path, outputs_dir: Path) -> Dict[str, Any]:
    """Acceptance criteria of prompt 4.4, read-only.

    - no_state_without_checkpoint: every completed book has a checkpoint that reports all chunks done.
    - no_job_stuck_running: no book in completed or needs_review has its latest job still active.
    - no_duplicate_suffix: no output file ends with a " (n).epub" suffix.
    """
    result: Dict[str, Any] = {
        "no_state_without_checkpoint": True,
        "no_job_stuck_running": True,
        "no_duplicate_suffix": True,
        "details": [],
    }
    conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT j.book_id, j.id, j.state, j.checkpoint_json, b.status
            FROM jobs j JOIN books b ON b.id = j.book_id
            WHERE j.id IN (SELECT MAX(id) FROM jobs GROUP BY book_id)
            """
        ).fetchall()
    finally:
        conn.close()
    for book_id, job_id, state, checkpoint_json, book_status in rows:
        if book_status in ("completed", "needs_review") and state in ACTIVE_STATES:
            result["no_job_stuck_running"] = False
            result["details"].append(f"book {book_id} is {book_status} but job {job_id} is {state}")
        if book_status == "completed":
            checkpoint = _checkpoint(checkpoint_json)
            done = checkpoint.get("upstream_completed_chunks")
            total = checkpoint.get("upstream_total_chunks")
            if done is None or total is None or int(done) < int(total):
                result["no_state_without_checkpoint"] = False
                result["details"].append(f"book {book_id} is completed without a full checkpoint")
    if outputs_dir.exists():
        duplicates = sorted(p.name for p in outputs_dir.glob("*.epub") if DUPLICATE_SUFFIX.search(p.name))
        if duplicates:
            result["no_duplicate_suffix"] = False
            result["details"].append(f"duplicate outputs: {', '.join(duplicates)}")
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run(command: List[str], *, timeout: float = 120, env: Optional[dict] = None):
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


def _container_path(path: Path) -> str:
    return "/app/" + path.relative_to(ROOT).as_posix()


def _start_mock() -> subprocess.Popen:
    env = {**os.environ, "MOCK_DELAY": "1.5"}
    process = subprocess.Popen(
        [sys.executable, str(MOCK)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{MOCK_PORT}/api/tags", timeout=1
            ) as response:
                if response.status == 200:
                    return process
        except Exception:
            time.sleep(0.2)
    process.terminate()
    raise RuntimeError("mock Ollama did not start")


def _translation_command(
    epub: Path,
    jobs_db: Path,
    output_name: str,
    translation_id: str,
) -> List[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(COMPOSE),
        "exec",
        "-T",
        "-e",
        "PYTHONUNBUFFERED=1",
        "-e",
        f"JOBS_DB_PATH={_container_path(jobs_db)}",
        "-e",
        f"OLLAMA_API_ENDPOINT=http://host.docker.internal:{MOCK_PORT}/api/generate",
        "-e",
        "OLLAMA_NUM_CTX=4096",
        "app",
        "python",
        "translate.py",
        "-i",
        _container_path(epub),
        "-o",
        f"/app/translated_files/{output_name}",
        "-sl",
        "English",
        "-tl",
        "Portuguese (Brazil)",
        "--provider",
        "ollama",
        "-m",
        "mock",
        "--no-color",
        "--translation-id",
        translation_id,
    ]


def _job_progress(jobs_db: Path, translation_id: str) -> Dict[str, Any]:
    if not jobs_db.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{jobs_db.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute(
                "SELECT status, progress FROM translation_jobs "
                "WHERE translation_id = ?",
                (translation_id,),
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    if row is None:
        return {}
    try:
        progress = json.loads(row["progress"] or "{}")
    except ValueError:
        progress = {}
    return {"status": row["status"], **progress}


def _wait_checkpoint(
    jobs_db: Path, translation_id: str, minimum: int, timeout: float
) -> Dict[str, Any]:
    deadline = time.time() + timeout
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = _job_progress(jobs_db, translation_id)
        if int(last.get("completed_chunks") or 0) >= minimum:
            return last
        time.sleep(0.5)
    return last


def _kill_translation(output_name: str) -> None:
    _run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "exec",
            "-T",
            "app",
            "python",
            "-m",
            "src.literary.kill_translation",
            output_name,
            "--signal",
            "KILL",
        ],
        timeout=30,
    )


def _outputs(base: str) -> List[str]:
    directory = ROOT / "translated_files"
    return sorted(
        path.name for path in directory.glob(f"{base}*.epub") if path.is_file()
    )


def _checkpoint_rows(jobs_db: Path, translation_id: str) -> int:
    if not jobs_db.exists():
        return 0
    try:
        con = sqlite3.connect(f"file:{jobs_db.as_posix()}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT COUNT(*) FROM checkpoint_chunks WHERE translation_id = ?",
                (translation_id,),
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return 0
    return int(row[0] if row else 0)


def _criteria(
    progress_after_kill: Dict[str, Any],
    total_chunks: int,
    outputs: List[str],
    status_after_complete: str,
    checkpoint_rows: int,
) -> Dict[str, Any]:
    completed = int(progress_after_kill.get("completed_chunks") or 0)
    no_state_without_checkpoint = True
    if completed > 0 and checkpoint_rows == 0:
        no_state_without_checkpoint = False
    if status_after_complete == "completed" and completed < total_chunks:
        no_state_without_checkpoint = False
    return {
        "no_state_without_checkpoint": no_state_without_checkpoint,
        "no_duplicate_suffix": not any(" (1)" in name for name in outputs),
        "no_job_stuck_running": status_after_complete != "running",
    }


def _kill_resume_phase(work: Path) -> Dict[str, Any]:
    """Kill at chunk 2, resume, then resume with the target already present."""
    epub = work / "test.epub"
    _run([sys.executable, str(BUILD_EPUB), str(epub)], timeout=30)
    jobs_db = work / "jobs.db"
    base = f"Destructive-24h-{work.name.split('-')[-1]}"
    translation_id = f"cli_24h_{work.name.split('-')[-1]}"
    log_one = work / "pass1.log"
    log_two = work / "pass2.log"
    log_three = work / "pass3.log"
    command = _translation_command(epub, jobs_db, f"{base}.epub", translation_id)

    with log_one.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        progress = _wait_checkpoint(jobs_db, translation_id, 2, timeout=60)
        _kill_translation(f"{base}.epub")
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    after_kill = _job_progress(jobs_db, translation_id)
    total = int(after_kill.get("total_chunks") or 6)
    completed_after_kill = int(after_kill.get("completed_chunks") or 0)

    with log_two.open("w", encoding="utf-8") as handle:
        second = subprocess.run(
            command,
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
        )
    after_resume = _job_progress(jobs_db, translation_id)
    outputs_after_resume = _outputs(base)

    with log_three.open("w", encoding="utf-8") as handle:
        third = subprocess.run(
            command,
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
        )
    after_second_resume = _job_progress(jobs_db, translation_id)
    outputs_after_second = _outputs(base)

    criteria = _criteria(
        after_kill,
        total,
        outputs_after_second,
        str(after_second_resume.get("status") or ""),
        _checkpoint_rows(jobs_db, translation_id),
    )
    return {
        "translation_id": translation_id,
        "after_kill": {
            "status": after_kill.get("status"),
            "completed_chunks": completed_after_kill,
            "total_chunks": total,
            "checkpoint_rows": _checkpoint_rows(jobs_db, translation_id),
        },
        "resume": {
            "exit_code": second.returncode,
            "status": after_resume.get("status"),
            "outputs": outputs_after_resume,
            "log": str(log_two),
        },
        "resume_with_existing_target": {
            "exit_code": third.returncode,
            "status": after_second_resume.get("status"),
            "outputs": outputs_after_second,
            "log": str(log_three),
        },
        "criteria": criteria,
        "log": str(log_one),
    }


def _db_recovery_phase(work: Path) -> Dict[str, Any]:
    completed = _run([sys.executable, str(RECOVERY)], timeout=180)
    return {
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "tail": (completed.stdout or "").strip().splitlines()[-3:],
    }


def _pause_control_phase(work: Path) -> Dict[str, Any]:
    db = work / "queue-pause.db"
    store = QueueStore(str(db))
    try:
        book_id = store.add_book(
            BookRecord(
                calibre_id=2,
                title="Pause Control",
                author="Test",
                languages=["en"],
                epub_path="",
            ),
            priority=1,
        )
        job_id = store.create_job(book_id, total_chapters=6)
    finally:
        store.close()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE books SET status = 'translating' WHERE id = ?", (book_id,))
        conn.execute("UPDATE jobs SET state = 'translating' WHERE id = ?", (job_id,))
        conn.commit()
    set_pause_now(db, True)
    requested = pause_now_requested(db)
    state = honor_pause_now(db, {"id": book_id, "title": "Pause Control"})
    honored = state.get("pause_now_honored_after") or {}
    return {
        "requested": requested,
        "honored": honored,
        "cleared": not state.get("pause_now"),
        "passed": requested and honored.get("id") == book_id and not state.get("pause_now"),
    }


def _app_health() -> str:
    completed = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Health.Status}}",
            "translatebook-literary-dev",
        ],
        timeout=30,
    )
    return (completed.stdout or "").strip()


def _app_restart_phase() -> Dict[str, Any]:
    started = time.time()
    _run(
        ["docker", "compose", "-f", str(COMPOSE), "restart", "app"],
        timeout=120,
    )
    deadline = time.time() + 120
    status = ""
    while time.time() < deadline:
        status = _app_health()
        if status == "healthy":
            break
        time.sleep(2)
    return {
        "status": status,
        "healthy_seconds": round(time.time() - started, 1),
        "passed": status == "healthy",
    }


def _run_window(args: argparse.Namespace) -> int:
    if not args.confirm_window:
        print("refusing window mode without --confirm-window", file=sys.stderr)
        return 2
    compose = Path(args.compose) if args.compose else None
    if compose is None or not compose.exists():
        print(
            "window mode needs a dedicated compose file "
            "(--compose docker-compose.destructive.yml)",
            file=sys.stderr,
        )
        return 2
    print(
        "window mode is a 24 h runbook: real queue, dedicated app instance, "
        "pause/resume, app restart mid-run and soak. "
        "This runner does not start it without the dedicated services.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["short", "window"], default="short")
    parser.add_argument("--app-restart", action="store_true")
    parser.add_argument("--confirm-window", action="store_true")
    parser.add_argument("--compose", default="")
    parser.add_argument("--preflight", action="store_true", help="only report whether the live stack is idle")
    parser.add_argument("--evaluate", type=Path, default=None, help="read-only: evaluate the criteria on a queue DB")
    parser.add_argument("--outputs", type=Path, default=None, help="outputs folder for --evaluate")
    args = parser.parse_args()
    if args.evaluate is not None:
        verdict = evaluate_criteria(args.evaluate, args.outputs or args.evaluate.parent)
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if all(verdict[name] for name in CRITERIA_NAMES) else 1
    compose = Path(args.compose) if args.compose else None
    check = preflight(args.mode, compose)
    print(json.dumps(check, ensure_ascii=False, indent=2))
    if args.preflight:
        return 0 if check["ready"] else EXIT_NOT_READY
    if not check["ready"]:
        print("not running: the live stack is busy or cannot be inspected", file=sys.stderr)
        return EXIT_NOT_READY
    if args.mode == "window":
        return _run_window(args)
    if args.app_restart:
        print(
            "--app-restart restarts the live container; it belongs to window mode on the dedicated instance",
            file=sys.stderr,
        )
        return 2

    work = ROOT / "data" / "tmp" / f"destructive-24h-{_stamp()}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"work dir: {work}")
    report: Dict[str, Any] = {
        "schema": "literary.destructive-24h",
        "schema_version": "1.0",
        "mode": "short",
        "started_at": _now(),
        "work_dir": str(work),
        "phases": {},
        "criteria": {},
        "window_items": [
            "queue-level pause/resume with a real translation",
            "app restart mid-translation on a dedicated app instance",
            "24 h soak with the real model and the live queue rules",
            "corruption of the queue DB (not only the jobs DB)",
        ],
    }

    mock = _start_mock()
    try:
        try:
            report["phases"]["db_recovery"] = _db_recovery_phase(work)
        except Exception as exc:
            report["phases"]["db_recovery"] = {"passed": False, "error": str(exc)}
        try:
            report["phases"]["kill_resume"] = _kill_resume_phase(work)
        except Exception as exc:
            report["phases"]["kill_resume"] = {"passed": False, "error": str(exc)}
        try:
            report["phases"]["pause_control"] = _pause_control_phase(work)
        except Exception as exc:
            report["phases"]["pause_control"] = {"passed": False, "error": str(exc)}
        if args.app_restart:
            try:
                report["phases"]["app_restart"] = _app_restart_phase()
            except Exception as exc:
                report["phases"]["app_restart"] = {"passed": False, "error": str(exc)}
    finally:
        mock.terminate()
        try:
            mock.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock.kill()

    kill = report["phases"].get("kill_resume") or {}
    report["criteria"] = kill.get("criteria") or {
        "no_state_without_checkpoint": False,
        "no_duplicate_suffix": False,
        "no_job_stuck_running": False,
    }
    report["finished_at"] = _now()
    (work / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Destructive 24 h — short run",
        "",
        f"- Work dir: `{work}`",
        f"- Started: {report['started_at']}",
        f"- Finished: {report['finished_at']}",
        "",
        "## Phases",
        "",
        "| Phase | Result |",
        "| --- | --- |",
    ]
    for name, phase in report["phases"].items():
        lines.append(f"| {name} | {'PASS' if phase.get('passed') else 'FAIL'} |")
    lines.extend(
        [
            "",
            "## Criteria",
            "",
            "| Criterion | Result |",
            "| --- | --- |",
        ]
    )
    for name, value in report["criteria"].items():
        lines.append(f"| {name} | {'PASS' if value else 'FAIL'} |")
    lines.extend(["", "## Window items", ""])
    lines.extend(f"- {item}" for item in report["window_items"])
    (work / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((work / "report.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
