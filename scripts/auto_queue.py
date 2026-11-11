"""Run the literary queue continuously with an automated audit gate.

The normal queue agent runs exactly one book and stops at ``needs_review``.
This script keeps the 24/7 workflow moving without skipping the gate:

1. wait while a book is preparing/translating;
2. when a book reaches ``needs_review``, run ``scripts/audit_book.py``;
3. only when every audit gate passes, approve the book and export Kindle;
4. start the next pending book; on any failure, stop and leave the book for
   human review.

By default the script runs as a supervisor around a worker process:

- the worker is restarted when it dies or stops heartbeating, with exponential
  backoff and at most ``--max-restarts-per-hour`` attempts in a rolling hour;
- a ``needs_review`` gate is never restarted: the supervisor stays online,
  writes ``blocked_gate`` to ``literary_queue.supervisor.json`` and waits for
  the book to leave the gate;
- the restart reason is written to the supervisor status file, the alerts log
  and the queue events, and ``queue status --json`` exposes it.

The audit is conservative: a missing key, an API error or a quality failure
stops the queue. The human review is replaced by the audit only for passes.

Usage:
    python scripts/auto_queue.py --max-books 0 --max-cloud-usd 0.05
    python scripts/auto_queue.py --no-supervise   # old single-process mode
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / "scripts" / "audit_book.py"
LEDGER = ROOT / "data" / "cost_ledger.jsonl"
ACTIVE_STATES = {"preparing", "translating", "reviewing", "validating"}

SUPERVISOR_SCHEMA = "literary-queue.supervisor"
SUPERVISOR_VERSION = "1.0"
GATE_REASONS = {"gate_needs_review", "needs_review"}
IN_PROGRESS_REASONS = {
    "active",
    "starting",
    "auditing",
    "retrying",
    "waiting_report",
}
STOP_REASONS = {
    "failed_book",
    "budget",
    "report_missing",
    "approval_failed",
    "no_pending",
    "max_books",
    "paused",
    "approved",
}

STATE_DIR = Path(os.getenv("AUTO_QUEUE_STATE_DIR", str(ROOT / "data")))
STATUS_PATH = STATE_DIR / "literary_queue.auto.json"
LOCK_PATH = STATE_DIR / "literary_queue.auto.lock"
SUPERVISOR_PATH = STATE_DIR / "literary_queue.supervisor.json"
RESTARTS_PATH = STATE_DIR / "literary_queue.restarts.json"
LOG_DIR = STATE_DIR / "queue-runs"
ALERTS_PATH = LOG_DIR / "supervisor-alerts.log"


def _configure_state_dir(path: Path) -> None:
    global STATE_DIR, STATUS_PATH, LOCK_PATH, SUPERVISOR_PATH, RESTARTS_PATH, LOG_DIR, ALERTS_PATH
    STATE_DIR = Path(path)
    STATUS_PATH = STATE_DIR / "literary_queue.auto.json"
    LOCK_PATH = STATE_DIR / "literary_queue.auto.lock"
    SUPERVISOR_PATH = STATE_DIR / "literary_queue.supervisor.json"
    RESTARTS_PATH = STATE_DIR / "literary_queue.restarts.json"
    LOG_DIR = STATE_DIR / "queue-runs"
    ALERTS_PATH = LOG_DIR / "supervisor-alerts.log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "book"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


_STATUS_LOCK = threading.Lock()
_LAST_STATUS: Dict[str, Any] = {}
HEARTBEAT_INTERVAL = 30.0


def _write_status(payload: Dict[str, Any]) -> None:
    with _STATUS_LOCK:
        data = {"heartbeat": _now(), "pid": os.getpid(), **payload}
        _LAST_STATUS.clear()
        _LAST_STATUS.update(data)
        _atomic_write(STATUS_PATH, data)


def _heartbeat_tick() -> None:
    with _STATUS_LOCK:
        if not _LAST_STATUS:
            return
        data = dict(_LAST_STATUS)
        data["heartbeat"] = _now()
        _LAST_STATUS.clear()
        _LAST_STATUS.update(data)
        _atomic_write(STATUS_PATH, data)


class _Heartbeat:
    """Refresh the worker status while a queue or audit command blocks."""

    def __init__(self, interval: float) -> None:
        self.interval = max(1.0, float(interval))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "_Heartbeat":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                _heartbeat_tick()
            except Exception:
                pass

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


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


def _term_targets(db: Path, book: Dict[str, Any]) -> Dict[str, str]:
    """Map each forbidden rendering to the glossary target for this book."""
    try:
        sys.path.insert(0, str(ROOT))
        from src.literary.queue import QueueStore
        from src.literary.resources import compile_for_book, load_tree
        from src.literary.run_plan import build_run_plan

        store = QueueStore(str(db))
        try:
            queued = store.get_book(int(book["id"]))
        finally:
            store.close()
        if queued is None:
            return {}
        plan = build_run_plan(queued)
        scopes = plan.get("scopes") or {}
        tree = load_tree(str(ROOT / "literary-resources"))
        compiled = compile_for_book(
            tree,
            scopes.get("author", ""),
            scopes.get("universe", ""),
            scopes.get("subseries", ""),
            scopes.get("book", ""),
            book_order=queued.series_index,
        )
        mapping: Dict[str, str] = {}
        for term in compiled.glossary.terms:
            for forbidden in getattr(term, "forbidden", []) or []:
                if forbidden and term.target:
                    mapping[str(forbidden).casefold()] = str(term.target)
        return mapping
    except Exception as exc:
        print(f"auto queue: could not load glossary terms: {exc}", flush=True)
        return {}


def _rewrite_epub_terms(
    path: Path, replacements: Dict[str, str], output: Optional[Path] = None
) -> Dict[str, int]:
    """Replace whole-word renderings in every text file of an EPUB."""
    import zipfile

    destination = output or path.with_name(f".{path.name}.termfix.tmp")
    counts: Dict[str, int] = {}
    normalized = {str(key).casefold(): value for key, value in replacements.items()}
    pattern = re.compile(
        r"(?<![\w])(" + "|".join(re.escape(key) for key in normalized) + r")(?![\w])",
        flags=re.I,
    )
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
        destination, "w", zipfile.ZIP_DEFLATED
    ) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.lower().endswith((".xhtml", ".html", ".htm", ".ncx", ".opf")):
                raw = data.decode("utf-8", "replace")

                def replace(match: re.Match[str]) -> str:
                    key = match.group(1).casefold()
                    counts[key] = counts.get(key, 0) + 1
                    target = normalized[key]
                    word = match.group(0)
                    if word.isupper():
                        return target.upper()
                    if word.islower():
                        return target.lower()
                    return target

                raw = pattern.sub(replace, raw)
                data = raw.encode("utf-8")
            target.writestr(item, data)
    if output is None:
        os.replace(destination, path)
    return counts


def _epubcheck(path: Path) -> Dict[str, Any]:
    from src.literary.queue_runner import _epubcheck as run_epubcheck

    return run_epubcheck(Path(path).resolve())


def _repair_forbidden(db: Path, book: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    """Apply glossary term fixes to the audited EPUB when nothing else failed.

    The queue runner already runs the reader repair with the Sun Eater terms.
    This is the last deterministic resort for a forbidden rendering that only
    lives in a text node the repair does not visit. The original file is kept
    until EPUBCheck accepts the rewritten copy.
    """
    reasons = [str(item) for item in (audit.get("reasons") or [])]
    if len(reasons) != 1 or "forbidden rendering" not in reasons[0]:
        return {"ok": False, "message": "not a forbidden-only failure"}
    hits = (audit.get("terms") or {}).get("forbidden_hits") or []
    raw_target = str(audit.get("target") or "").strip()
    target = Path(raw_target) if raw_target else None
    if not hits or target is None or not target.is_file():
        return {"ok": False, "message": "no target or no forbidden hits"}
    mapping = _term_targets(db, book)
    replacements = {
        str(hit["forbidden"]).casefold(): mapping.get(str(hit["forbidden"]).casefold(), "")
        for hit in hits
    }
    replacements = {key: value for key, value in replacements.items() if value}
    if not replacements:
        return {"ok": False, "message": "no glossary target for the forbidden forms"}
    backup = target.with_name(f"{target.stem}.pre-termfix{target.suffix}")
    fixed = target.with_name(f".{target.stem}.termfix{target.suffix}")
    if backup.exists():
        backup.unlink()
    if fixed.exists():
        fixed.unlink()
    try:
        counts = _rewrite_epub_terms(target, replacements, fixed)
        check = _epubcheck(fixed)
        if check.get("errors") != 0:
            fixed.unlink(missing_ok=True)
            return {
                "ok": False,
                "message": f"EPUBCheck rejected the term fix: {check.get('errors')} errors",
            }
        target.replace(backup)
        os.replace(fixed, target)
    except Exception as exc:
        fixed.unlink(missing_ok=True)
        if not target.exists() and backup.exists():
            backup.replace(target)
        return {"ok": False, "message": f"term fix failed: {exc}"}
    print(f"auto queue: term fix applied to {target.name}: {counts}", flush=True)
    return {"ok": True, "changes": counts, "message": "term fix applied"}


def _can_retry(
    book: Dict[str, Any],
    job: Optional[Dict[str, Any]],
    retries: Dict[int, int],
    max_retries: int,
) -> bool:
    """Only retry a crashed run that still owns a resumable checkpoint."""
    if max_retries <= 0 or not job:
        return False
    if retries.get(int(book["id"]), 0) >= max_retries:
        return False
    if not str(job.get("translation_id") or "").strip():
        return False
    error = str(job.get("error") or "").casefold()
    if "gate" in error or "paused by user" in error:
        return False
    return True


def _requeue_failed(db: Path, book: Dict[str, Any], job: Dict[str, Any]) -> int:
    """Send a failed book back to the queue so the runner resumes its checkpoint."""
    if _run(
        [
            sys.executable,
            "-m",
            "src.literary.cli",
            "queue",
            "set-job-state",
            "--db",
            str(db),
            "--job-id",
            str(job["id"]),
            "--state",
            "paused",
            "--message",
            "automatic retry after a failed run",
        ],
        LOG_DIR / "auto-retry.log",
    ) != 0:
        return 1
    return _run(
        [
            sys.executable,
            "-m",
            "src.literary.cli",
            "queue",
            "set-state",
            "--db",
            str(db),
            "--book-id",
            str(book["id"]),
            "--state",
            "pending",
            "--message",
            "automatic retry after a failed run",
        ],
        LOG_DIR / "auto-retry.log",
    )


def _audit_command(
    *, book_id: int, job_id: int, report: Path, out_dir: Path, max_cloud_usd: float
) -> List[str]:
    return [
        sys.executable,
        str(DEFAULT_AUDIT),
        "--book-id",
        str(book_id),
        "--job-id",
        str(job_id),
        "--report",
        str(report),
        "--max-cloud-usd",
        str(max_cloud_usd),
        "--out",
        str(out_dir),
    ]


def run_worker(args: argparse.Namespace) -> int:
    if not args.db.exists():
        raise SystemExit(f"queue database not found: {args.db}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"auto-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.log"
    print(f"auto queue: log={log_path}", flush=True)

    heartbeat = _Heartbeat(HEARTBEAT_INTERVAL)
    heartbeat.__enter__()
    started = 0
    retries: Dict[int, int] = {}
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
                        "reason": "active",
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
                job = _latest_job(args.db, book["id"])
                if _can_retry(book, job, retries, args.max_retries):
                    retries[book["id"]] = retries.get(book["id"], 0) + 1
                    if _requeue_failed(args.db, book, job) == 0:
                        _write_status(
                            {
                                "running": True,
                                "phase": "retrying",
                                "reason": "retrying",
                                "book_id": book["id"],
                                "title": book["title"],
                                "message": "automatic retry from the last checkpoint",
                            }
                        )
                        continue
                _write_status(
                    {
                        "running": False,
                        "phase": "blocked",
                        "reason": "failed_book",
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
                            "reason": "needs_review",
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
                                "reason": "report_missing",
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
                            "reason": "waiting_report",
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
                            "reason": "budget",
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
                        "reason": "auditing",
                        "book_id": book["id"],
                        "title": book["title"],
                        "message": "running audit",
                    }
                )
                command = _audit_command(
                    book_id=book["id"],
                    job_id=job["id"],
                    report=report,
                    out_dir=audit_dir,
                    max_cloud_usd=args.max_cloud_usd,
                )
                code = _run(command, log_path)
                audit = _read_json(audit_dir / "audit.json")
                if code != 0 or not audit.get("passed"):
                    repair = _repair_forbidden(args.db, book, audit)
                    if repair.get("ok"):
                        audit_dir = audit_dir.with_name(audit_dir.name + "-termfix")
                        command = _audit_command(
                            book_id=book["id"],
                            job_id=job["id"],
                            report=report,
                            out_dir=audit_dir,
                            max_cloud_usd=args.max_cloud_usd,
                        )
                        code = _run(command, log_path)
                        audit = _read_json(audit_dir / "audit.json")
                if code != 0 or not audit.get("passed"):
                    _write_status(
                        {
                            "running": False,
                            "phase": "blocked",
                            "reason": "gate_needs_review",
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
                            "reason": "approval_failed",
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
                        "reason": "approved",
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
                _write_status({"running": False, "phase": "idle", "reason": "no_pending", "message": "no pending books"})
                print("auto queue: no pending books", flush=True)
                return 0
            if args.max_books and started >= args.max_books:
                _write_status({"running": False, "phase": "idle", "reason": "max_books", "message": "max books reached"})
                return 0

            book = pending[0]
            _write_status(
                {
                    "running": True,
                    "phase": "starting",
                    "reason": "starting",
                    "book_id": book["id"],
                    "title": book["title"],
                    "message": "starting queue runner",
                }
            )
            run_started = _now()
            code = _run(_queue_command(args.db), log_path)
            if args.once:
                return 0 if code == 0 else 1
            # A pause-now is a stop request for the whole queue, not a request
            # to advance to the next pending book. The queue runner honours it
            # mid-book; the supervisor must stop here instead of picking the
            # next pending title.
            control = _read_json(ROOT / "data" / "literary_queue.control.json")
            honored = control.get("pause_now_honored_after") or {}
            honored_at = str(control.get("pause_now_honored_at") or "")
            if honored.get("id") == book["id"] and honored_at >= run_started:
                _write_status({
                    "running": False,
                    "phase": "paused",
                    "reason": "paused",
                    "book_id": book["id"],
                    "title": book["title"],
                    "message": "pause-now honored; queue stopped",
                })
                print(f"auto queue: pause-now honored for {book['title']}; queue stopped", flush=True)
                return 0
            if code != 0:
                failed_book = next(
                    (item for item in _books(args.db) if item["id"] == book["id"]), None
                )
                failed_job = _latest_job(args.db, book["id"])
                if (
                    failed_book
                    and failed_book["status"] == "failed"
                    and _can_retry(failed_book, failed_job, retries, args.max_retries)
                ):
                    retries[failed_book["id"]] = retries.get(failed_book["id"], 0) + 1
                    if _requeue_failed(args.db, failed_book, failed_job) == 0:
                        _write_status(
                            {
                                "running": True,
                                "phase": "retrying",
                                "reason": "retrying",
                                "book_id": failed_book["id"],
                                "title": failed_book["title"],
                                "message": "automatic retry from the last checkpoint",
                            }
                        )
                        print(
                            f"auto queue: retrying {failed_book['title']} from checkpoint",
                            flush=True,
                        )
                        continue
                _write_status(
                    {
                        "running": False,
                        "phase": "blocked",
                        "reason": "runner_failed",
                        "book_id": book["id"],
                        "title": book["title"],
                        "message": f"queue runner exited {code}",
                    }
                )
                return 1
            # The loop re-reads the queue and audits the book that just stopped.
    finally:
        heartbeat.__exit__()


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _acquire_lock() -> bool:
    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)
            print(f"auto queue: already running (pid {old_pid})", flush=True)
            return False
        except (ValueError, OSError):
            pass
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except OSError:
        pass


def _notify(db: Path, message: str, level: str = "warning") -> None:
    """Durable notification: log, status edge and queue event."""
    line = f"[{_now()}] {level}: {message}"
    print(f"supervisor: {message}", flush=True)
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ALERTS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    try:
        from src.literary.queue import QueueStore

        store = QueueStore(str(db))
        try:
            store.add_event(message, level=level)
        finally:
            store.close()
    except Exception:
        pass


def _read_worker_status() -> Dict[str, Any]:
    return _read_json(STATUS_PATH)


def _heartbeat_age(worker_pid: int, started_at: str) -> Optional[float]:
    status = _read_worker_status()
    if int(status.get("pid") or 0) != int(worker_pid):
        return None
    stamp = _parse_iso(status.get("heartbeat"))
    if stamp is None:
        try:
            stamp = datetime.fromtimestamp(STATUS_PATH.stat().st_mtime, timezone.utc)
        except OSError:
            return None
    return max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())


def _since(started_at: str) -> float:
    stamp = _parse_iso(started_at)
    if stamp is None:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())


def _load_restarts() -> List[str]:
    data = _read_json(RESTARTS_PATH)
    return [str(item) for item in data.get("attempts") or [] if item]


def _recent_attempts(now: float, history: List[str]) -> List[str]:
    cutoff = now - 3600
    recent = []
    for item in history:
        stamp = _parse_iso(item)
        if stamp is not None and stamp.timestamp() >= cutoff:
            recent.append(item)
    return recent


def _budget_exhausted(history: List[str], max_per_hour: int) -> bool:
    return len(_recent_attempts(time.time(), history)) >= max(1, max_per_hour)


def _record_restart(reason: str) -> List[str]:
    now = time.time()
    history = _recent_attempts(now, _load_restarts())
    history.append(_now())
    history = history[-100:]
    _atomic_write(
        RESTARTS_PATH,
        {"attempts": history, "last_reason": reason, "last_at": _now()},
    )
    return history


def _backoff_seconds(attempt: int, base: float, cap: float) -> float:
    base = max(1.0, float(base))
    cap = max(base, float(cap))
    return min(cap, base * (2 ** max(0, attempt - 1)))


def _classify_exit(
    exit_code: int, status: Dict[str, Any], stalled: bool = False
) -> tuple[str, str]:
    """Return ``(action, reason)`` for a finished worker.

    ``hold`` is the gate: the supervisor stays alive but never restarts the
    worker while a book is in ``needs_review``. ``stop`` is a terminal state
    (idle, paused, failed book, budget). ``restart`` is a crash or a stall.
    """
    reason = str(status.get("reason") or "").strip()
    if reason in IN_PROGRESS_REASONS or not reason:
        if stalled:
            reason = "worker_stalled"
        elif exit_code == 0:
            reason = "worker_exited"
        else:
            reason = "worker_died"
    if reason in GATE_REASONS:
        return "hold", reason
    if stalled:
        return "restart", reason
    if exit_code == 0:
        return "stop", reason
    if reason in STOP_REASONS:
        return "stop", reason
    return "restart", reason


def _has_gate_book(db: Path) -> bool:
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            return (
                con.execute(
                    "SELECT 1 FROM books WHERE status = 'needs_review' LIMIT 1"
                ).fetchone()
                is not None
            )
        finally:
            con.close()
    except sqlite3.Error:
        return True


def _worker_command(args: argparse.Namespace) -> List[str]:
    override = os.getenv("AUTO_QUEUE_WORKER_SCRIPT", "").strip()
    if override:
        return [sys.executable, override]
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--db",
        str(args.db),
        "--state-dir",
        str(STATE_DIR),
        "--max-books",
        str(args.max_books),
        "--max-cloud-usd",
        str(args.max_cloud_usd),
        "--max-total-cloud-usd",
        str(args.max_total_cloud_usd),
        "--interval",
        str(args.interval),
        "--max-retries",
        str(args.max_retries),
        "--heartbeat-interval",
        str(args.heartbeat_interval),
    ]
    if args.once:
        command.append("--once")
    return command


def _restart_state(
    args: argparse.Namespace,
    history: List[str],
    *,
    reason: Optional[str] = None,
    next_attempt_at: Optional[str] = None,
    backoff_s: Optional[float] = None,
) -> Dict[str, Any]:
    recent = _recent_attempts(time.time(), history)
    data = _read_json(RESTARTS_PATH)
    return {
        "attempts_last_hour": len(recent),
        "max_per_hour": args.max_restarts_per_hour,
        "last_reason": reason or data.get("last_reason"),
        "last_at": data.get("last_at"),
        "next_attempt_at": next_attempt_at,
        "backoff_s": backoff_s,
    }


def _worker_info(
    pid: int,
    running: bool,
    started_at: str,
    exit_code: Optional[int] = None,
    heartbeat_age_s: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "pid": pid,
        "running": running,
        "started_at": started_at,
        "exit_code": exit_code,
        "heartbeat_age_s": round(heartbeat_age_s, 1)
        if heartbeat_age_s is not None
        else None,
    }


def _write_supervisor_status(
    state: str,
    *,
    worker: Dict[str, Any],
    restart: Dict[str, Any],
    message: str,
) -> None:
    _atomic_write(
        SUPERVISOR_PATH,
        {
            "schema": SUPERVISOR_SCHEMA,
            "schema_version": SUPERVISOR_VERSION,
            "pid": os.getpid(),
            "heartbeat": _now(),
            "state": state,
            "message": message,
            "worker": worker,
            "restart": restart,
        },
    )


def _sleep_with_status(
    seconds: float,
    *,
    state: str,
    worker: Dict[str, Any],
    restart: Dict[str, Any],
    message: str,
) -> None:
    deadline = time.time() + max(0.0, seconds)
    while True:
        _write_supervisor_status(
            state, worker=worker, restart=restart, message=message
        )
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(10.0, remaining))


def _kill_worker(process: subprocess.Popen) -> None:
    """Kill the worker and its child runner, not just the worker process."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except OSError:
            process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    except OSError:
        pass


def run_supervisor(args: argparse.Namespace) -> int:
    if not args.db.exists():
        raise SystemExit(f"queue database not found: {args.db}")
    if not _acquire_lock():
        raise SystemExit(1)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"supervisor-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.log"
    log_handle = log_path.open("a", encoding="utf-8", buffering=1)
    print(f"supervisor: log={log_path}", flush=True)

    history = _load_restarts()
    restart = _restart_state(args, history)
    process: Optional[subprocess.Popen] = None
    try:
        while True:
            command = _worker_command(args)
            log_handle.write(
                f"[{_now()}] supervisor: starting worker: {' '.join(command)}\n"
            )
            started_at = _now()
            popen_kwargs = {"start_new_session": True} if os.name != "nt" else {}
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                **popen_kwargs,
            )
            stalled = False
            while process.poll() is None:
                age = _heartbeat_age(process.pid, started_at)
                elapsed = _since(started_at)
                effective_age = age if age is not None else elapsed
                if (
                    elapsed > args.startup_grace
                    and effective_age > args.heartbeat_timeout
                ):
                    log_handle.write(
                        f"[{_now()}] supervisor: heartbeat {effective_age:.1f}s > "
                        f"{args.heartbeat_timeout:.0f}s; killing worker {process.pid}\n"
                    )
                    _kill_worker(process)
                    stalled = True
                    break
                _write_supervisor_status(
                    "running",
                    worker=_worker_info(
                        process.pid, True, started_at, heartbeat_age_s=age
                    ),
                    restart=restart,
                    message="worker active",
                )
                time.sleep(args.supervise_interval)

            exit_code = int(process.returncode if process.returncode is not None else -1)
            status = _read_worker_status()
            if int(status.get("pid") or 0) != int(process.pid):
                status = {}
            action, reason = _classify_exit(exit_code, status, stalled)
            log_handle.write(
                f"[{_now()}] supervisor: worker exit code={exit_code} "
                f"reason={reason} action={action}\n"
            )

            if action == "hold":
                message = str(status.get("message") or reason)
                log_handle.write(
                    f"[{_now()}] supervisor: gate hold: {reason} "
                    f"({message}); not restarting\n"
                )
                _notify(args.db, f"gate hold: {reason} ({message}); not restarting")
                _write_supervisor_status(
                    "blocked_gate",
                    worker=_worker_info(process.pid, False, started_at, exit_code),
                    restart=_restart_state(args, history, reason=reason),
                    message=f"gate hold: {message}",
                )
                while _has_gate_book(args.db):
                    _write_supervisor_status(
                        "blocked_gate",
                        worker=_worker_info(process.pid, False, started_at, exit_code),
                        restart=_restart_state(args, history, reason=reason),
                        message=f"gate hold: {message}",
                    )
                    time.sleep(min(10.0, max(0.5, args.gate_poll_interval)))
                log_handle.write(f"[{_now()}] supervisor: gate cleared; resuming\n")
                continue

            if action == "stop":
                _notify(args.db, f"supervisor stop: {reason}")
                _write_supervisor_status(
                    "stopped",
                    worker=_worker_info(process.pid, False, started_at, exit_code),
                    restart=_restart_state(args, history, reason=reason),
                    message=str(status.get("message") or reason),
                )
                return 0 if exit_code == 0 else 1

            recent = _recent_attempts(time.time(), history)
            if _budget_exhausted(history, args.max_restarts_per_hour):
                _notify(
                    args.db,
                    f"restart budget exhausted: {len(recent)}/"
                    f"{args.max_restarts_per_hour} in 1h; last={reason}",
                    level="error",
                )
                _write_supervisor_status(
                    "halted",
                    worker=_worker_info(process.pid, False, started_at, exit_code),
                    restart=_restart_state(args, history, reason=reason),
                    message="restart budget exhausted",
                )
                return 1

            history = _record_restart(reason)
            attempt = len(_recent_attempts(time.time(), history))
            backoff = _backoff_seconds(
                attempt, args.restart_backoff, args.restart_backoff_max
            )
            next_at = _iso(time.time() + backoff)
            _notify(
                args.db,
                f"restart {attempt}/{args.max_restarts_per_hour} in 1h: "
                f"{reason}; backoff {backoff:.0f}s",
            )
            log_handle.write(
                f"[{_now()}] supervisor: restarting in {backoff:.0f}s "
                f"(attempt {attempt}/{args.max_restarts_per_hour} in 1h)\n"
            )
            restart = _restart_state(
                args,
                history,
                reason=reason,
                next_attempt_at=next_at,
                backoff_s=backoff,
            )
            _sleep_with_status(
                backoff,
                state="backoff",
                worker=_worker_info(process.pid, False, started_at, exit_code),
                restart=restart,
                message=f"backoff {backoff:.0f}s after {reason}",
            )
            restart = _restart_state(args, history, reason=reason)
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            _kill_worker(process)
        _write_supervisor_status(
            "stopped",
            worker=_worker_info(process.pid if process else 0, False, _now()),
            restart=_restart_state(args, history, reason="interrupted"),
            message="supervisor interrupted",
        )
        return 0
    finally:
        if process is not None and process.poll() is None:
            _kill_worker(process)
        log_handle.close()
        _release_lock()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--max-books", type=int, default=0, help="0 = all pending books")
    parser.add_argument("--max-cloud-usd", type=float, default=0.05)
    parser.add_argument("--max-total-cloud-usd", type=float, default=0.50)
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=1, help="automatic retries per failed book")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-supervise", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--heartbeat-interval", type=float, default=30.0)
    parser.add_argument("--heartbeat-timeout", type=float, default=600.0)
    parser.add_argument("--supervise-interval", type=float, default=5.0)
    parser.add_argument("--startup-grace", type=float, default=120.0)
    parser.add_argument("--restart-backoff", type=float, default=30.0)
    parser.add_argument("--restart-backoff-max", type=float, default=900.0)
    parser.add_argument("--max-restarts-per-hour", type=int, default=3)
    parser.add_argument("--gate-poll-interval", type=float, default=30.0)
    args = parser.parse_args()

    if args.state_dir is not None:
        _configure_state_dir(args.state_dir)
    args.db = Path(args.db) if args.db is not None else STATE_DIR / "literary_queue.db"

    global HEARTBEAT_INTERVAL
    HEARTBEAT_INTERVAL = max(1.0, args.heartbeat_interval)

    if args.worker:
        return run_worker(args)
    if args.no_supervise:
        if not _acquire_lock():
            return 1
        try:
            return run_worker(args)
        finally:
            _release_lock()
    return run_supervisor(args)


if __name__ == "__main__":
    raise SystemExit(main())
