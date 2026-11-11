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
                    return normalized[key]

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--max-books", type=int, default=0, help="0 = all pending books")
    parser.add_argument("--max-cloud-usd", type=float, default=0.05)
    parser.add_argument("--max-total-cloud-usd", type=float, default=0.50)
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=1, help="automatic retries per failed book")
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
