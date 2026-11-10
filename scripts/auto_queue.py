"""Run the literary queue continuously with an automated audit gate.

The normal queue agent runs exactly one book and stops at ``needs_review``.
This supervisor keeps the 24/7 workflow moving without skipping the gate:

1. wait while a book is preparing/translating;
2. when a book reaches ``needs_review``, run ``scripts/audit_book.py``;
3. only when every audit gate passes, approve the book and export Kindle;
4. start the next pending book; on any failure, stop and leave the book for
   human review.

The audit is conservative: a missing key, an API error or a quality failure
stops the queue. The human review is replaced by the audit only for passes.

Usage:
    python scripts/auto_queue.py --max-books 0 --max-cloud-usd 0.05
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
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "literary_queue.db"
DEFAULT_AUDIT = ROOT / "scripts" / "audit_book.py"
STATUS_PATH = ROOT / "data" / "literary_queue.auto.json"
LOCK_PATH = ROOT / "data" / "literary_queue.auto.lock"
LOG_DIR = ROOT / "data" / "queue-runs"
LEDGER = ROOT / "data" / "cost_ledger.jsonl"
ACTIVE_STATES = {"preparing", "translating", "reviewing", "validating"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "book"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(payload: Dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"heartbeat": _now(), **payload}
    temporary = STATUS_PATH.with_name(STATUS_PATH.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATUS_PATH)


def _books(db: Path) -> List[Dict[str, Any]]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in con.execute(
            """select id,title,status,priority,series,series_index,provider,model,word_count
               from books order by priority desc, series, coalesce(series_index,0), id"""
        )
    ]
    con.close()
    return rows


def _latest_job(db: Path, book_id: int) -> Optional[Dict[str, Any]]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "select id,state,current_chapter,total_chapters,translation_id,error from jobs where book_id=? order by id desc limit 1",
        (book_id,),
    ).fetchone()
    con.close()
    return dict(row) if row else None


def _audit_spend() -> float:
    total = 0.0
    try:
        text = LEDGER.read_text(encoding="utf-8")
    except OSError:
        return total
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("stage") == "auto-audit":
            total += float(row.get("cost_usd") or 0)
    return total


def _run(command: List[str], log_path: Path) -> int:
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[{_now()}] $ {' '.join(command)}\n")
        log.flush()
        process = subprocess.run(
            command,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log.write(f"[{_now()}] exit {process.returncode}\n")
    return process.returncode


def _queue_command(db: Path) -> List[str]:
    return [
        sys.executable,
        "-m",
        "src.literary.cli",
        "queue",
        "run-all",
        "--db",
        str(db),
        "--parallel",
        "1",
        "--refine-limit",
        "0",
        "--max-books",
        "1",
        "--stop-on-review",
        "--outputs",
        "translated_files",
        "--kindle-out",
        "translated_files/kindle",
    ]


def _approve(db: Path, book_id: int, job_id: int, message: str) -> int:
    return _run(
        [
            sys.executable,
            "-m",
            "src.literary.cli",
            "queue",
            "approve",
            "--db",
            str(db),
            "--book-id",
            str(book_id),
            "--job-id",
            str(job_id),
            "--message",
            message,
        ],
        LOG_DIR / "auto-approve.log",
    )


def _export_kindle(db: Path) -> int:
    return _run(
        [
            sys.executable,
            "-m",
            "src.literary.cli",
            "queue",
            "export-kindle",
            "--db",
            str(db),
            "--outputs",
            "translated_files",
            "--out",
            "translated_files/kindle",
        ],
        LOG_DIR / "auto-export.log",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--max-books", type=int, default=0, help="0 = all pending books")
    parser.add_argument("--max-cloud-usd", type=float, default=0.05)
    parser.add_argument("--max-total-cloud-usd", type=float, default=0.50)
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"queue database not found: {args.db}")
    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)
            raise SystemExit(f"auto queue already running (pid {old_pid})")
        except (ValueError, OSError):
            pass
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"auto-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.log"
    print(f"auto queue: log={log_path}", flush=True)

    started = 0
    report_waits: Dict[int, float] = {}
    try:
        while True:
            books = _books(args.db)
            runner = _read_json(ROOT / "data" / "literary_queue.runner.json")
            active = [book for book in books if book["status"] in ACTIVE_STATES]
            if active or runner.get("running"):
                book = active[0] if active else next(
                    (item for item in books if item["id"] == runner.get("book_id")),
                    {"id": 0, "title": "runner"},
                )
                _write_status(
                    {
                        "running": True,
                        "phase": "waiting",
                        "book_id": book.get("id"),
                        "title": book.get("title"),
                        "message": "translation active",
                    }
                )
                if args.once:
                    return 0
                time.sleep(args.interval)
                continue

            failed = [book for book in books if book["status"] == "failed"]
            if failed:
                book = failed[0]
                _write_status(
                    {
                        "running": False,
                        "phase": "blocked",
                        "book_id": book["id"],
                        "title": book["title"],
                        "message": "book failed; human review required",
                    }
                )
                print(f"auto queue: blocked on failed book {book['title']}", flush=True)
                return 1

            needs = [book for book in books if book["status"] == "needs_review"]
            if needs:
                book = needs[0]
                job = _latest_job(args.db, book["id"])
                if not job:
                    _write_status(
                        {
                            "running": False,
                            "phase": "blocked",
                            "book_id": book["id"],
                            "title": book["title"],
                            "message": "needs_review without a job",
                        }
                    )
                    return 1
                report = LOG_DIR / f"{_slug(book['title'])}.report.json"
                if not report.exists():
                    first_seen = report_waits.setdefault(book["id"], time.time())
                    if time.time() - first_seen > 600:
                        _write_status(
                            {
                                "running": False,
                                "phase": "blocked",
                                "book_id": book["id"],
                                "title": book["title"],
                                "message": f"report missing after 10 minutes: {report}",
                            }
                        )
                        return 1
                    _write_status(
                        {
                            "running": True,
                            "phase": "waiting",
                            "book_id": book["id"],
                            "title": book["title"],
                            "message": "waiting for queue report",
                        }
                    )
                    if args.once:
                        return 0
                    time.sleep(args.interval)
                    continue
                report_waits.pop(book["id"], None)
                audit_dir = ROOT / "data" / "audits" / f"{_slug(book['title'])}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
                spend = _audit_spend()
                if spend + args.max_cloud_usd > args.max_total_cloud_usd:
                    _write_status(
                        {
                            "running": False,
                            "phase": "blocked",
                            "book_id": book["id"],
                            "title": book["title"],
                            "message": f"audit budget would exceed ${args.max_total_cloud_usd:.2f} (spent ${spend:.4f})",
                        }
                    )
                    return 1
                _write_status(
                    {
                        "running": True,
                        "phase": "auditing",
                        "book_id": book["id"],
                        "title": book["title"],
                        "message": "running audit",
                    }
                )
                command = [
                    sys.executable,
                    str(DEFAULT_AUDIT),
                    "--book-id",
                    str(book["id"]),
                    "--job-id",
                    str(job["id"]),
                    "--report",
                    str(report),
                    "--max-cloud-usd",
                    str(args.max_cloud_usd),
                    "--out",
                    str(audit_dir),
                ]
                code = _run(command, log_path)
                audit = _read_json(audit_dir / "audit.json")
                if code != 0 or not audit.get("passed"):
                    _write_status(
                        {
                            "running": False,
                            "phase": "blocked",
                            "book_id": book["id"],
                            "title": book["title"],
                            "message": "audit failed; human review required",
                            "audit": str(audit_dir / "audit.md"),
                            "reasons": audit.get("reasons", []),
                        }
                    )
                    print(f"auto queue: audit failed for {book['title']}; see {audit_dir / 'audit.md'}", flush=True)
                    return 1
                message = f"auto-approved by audit: {audit_dir.name}"
                if _approve(args.db, book["id"], job["id"], message) != 0:
                    _write_status(
                        {
                            "running": False,
                            "phase": "blocked",
                            "book_id": book["id"],
                            "title": book["title"],
                            "message": "approval command failed",
                        }
                    )
                    return 1
                _export_kindle(args.db)
                started += 1
                _write_status(
                    {
                        "running": True,
                        "phase": "approved",
                        "book_id": book["id"],
                        "title": book["title"],
                        "message": message,
                        "audit": str(audit_dir / "audit.md"),
                    }
                )
                if args.once:
                    return 0
                continue

            pending = [book for book in books if book["status"] == "pending"]
            if not pending:
                _write_status({"running": False, "phase": "idle", "message": "no pending books"})
                print("auto queue: no pending books", flush=True)
                return 0
            if args.max_books and started >= args.max_books:
                _write_status({"running": False, "phase": "idle", "message": "max books reached"})
                return 0

            book = pending[0]
            _write_status(
                {
                    "running": True,
                    "phase": "starting",
                    "book_id": book["id"],
                    "title": book["title"],
                    "message": "starting queue runner",
                }
            )
            code = _run(_queue_command(args.db), log_path)
            if args.once:
                return 0 if code == 0 else 1
            if code != 0:
                _write_status(
                    {
                        "running": False,
                        "phase": "blocked",
                        "book_id": book["id"],
                        "title": book["title"],
                        "message": f"queue runner exited {code}",
                    }
                )
                return 1
            # The loop re-reads the queue and audits the book that just stopped.
    finally:
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
