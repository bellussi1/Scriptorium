"""Upsert the running queue job's estimated cloud spend into the cost ledger.

The queue runner does not persist provider token counts for every provider, so
this uses the book's word count and the job's completed-chunk ratio at a measured
per-million-word rate. The row is marked `estimated` and replaced on each run, so
the ledger does not accumulate partial duplicates.

The queue database progress can lag chapter boundaries; when the book's queue
log has a later `Updated main checkpoint with global stats` line, that count
wins and `progress_source` is `log`.

Usage:
    python scripts/lit_queue_cost.py --book-id 8
    python scripts/lit_queue_cost.py --book-id 8 --rate-usd-per-million 14.76
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
QUEUE_DB = ROOT / "data" / "literary_queue.db"
LEDGER = ROOT / "data" / "cost_ledger.jsonl"


def _read_ledger(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _log_progress(path: Optional[Path], title: str) -> Tuple[int, int]:
    """Return the last global chunk checkpoint written to the queue log."""
    if path is None:
        path = ROOT / "data" / "queue-runs" / f"{_slug(title)}.log"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0
    matches = re.findall(
        r"Updated main checkpoint with global stats:\s*(\d+)/(\d+) chunks",
        text,
    )
    if not matches:
        return 0, 0
    done, total = matches[-1]
    return int(done), int(total)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-id", type=int, default=8)
    parser.add_argument("--rate-usd-per-million", type=float, default=14.76)
    parser.add_argument("--db", type=Path, default=QUEUE_DB)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Queue log to read when the DB progress lags; defaults to data/queue-runs/<book>.log",
    )
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"queue database not found: {args.db}")
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    book = con.execute(
        "select id, title, provider, model, word_count from books where id = ?",
        (args.book_id,),
    ).fetchone()
    job = con.execute(
        """select id, state, current_chapter, total_chapters, translation_id, updated_at
           from jobs where book_id = ? order by id desc limit 1""",
        (args.book_id,),
    ).fetchone()
    con.close()
    if not book or not job:
        raise SystemExit(f"book {args.book_id} or its latest job not found")

    db_total = int(job["total_chapters"] or 0)
    db_done = int(job["current_chapter"] or 0)
    log_done, log_total = _log_progress(args.log, str(book["title"] or ""))
    total = max(db_total, log_total)
    done = max(db_done, log_done)
    if total <= 0:
        raise SystemExit("job has no total chunk count yet")
    words_done = float(book["word_count"] or 0) * done / total
    cost = words_done * args.rate_usd_per_million / 1_000_000
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": str(book["provider"] or "unknown"),
        "model": str(book["model"] or "unknown"),
        "book": str(book["title"] or ""),
        "stage": "queue-running",
        "job_id": int(job["id"]),
        "translation_id": str(job["translation_id"] or ""),
        "chunks_done": done,
        "chunks_total": total,
        "db_chunks_done": db_done,
        "progress_source": "log" if done > db_done else "db",
        "words_done": round(words_done, 1),
        "cost_usd": round(cost, 4),
        "estimated": True,
        "notes": (
            f"partial at {done}/{total} chunks; "
            f"per-word estimate at US$ {args.rate_usd_per_million}/M"
        ),
    }

    rows = [
        item
        for item in _read_ledger(args.ledger)
        if not (
            item.get("stage") == "queue-running"
            and int(item.get("job_id") or 0) == int(job["id"])
        )
    ]
    rows.append(row)
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    args.ledger.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
