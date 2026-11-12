"""Inventory and repair of the chunks that fell back during a literary translation.

A chunk falls back when the model's reply could not be used as-is. The job's
progress keeps two indexes of those chunks, both written per EPUB file:

- ``epub_degraded_units``: chunks that were translated but whose inline tags
  were only approximately repositioned (token alignment).
- ``epub_fallback_units``: the reason and attempt count of each of those chunks,
  plus chunks left in the source language. Reasons are "placeholder", "raw" and
  "api" (see xhtml_translation_state.FALLBACK_REASONS).

The repair re-enters the book through the normal translation path with
``--retry-token-aligned``: the resume then re-translates exactly the chunks in
those indexes plus any chunk still unfinished, and rebuilds the EPUB.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

# Book states in which a repair may change the EPUB. "approved" books are
# closed by a human review and are not reopened by this command.
REPAIRABLE_BOOK_STATES = frozenset({"needs_review", "paused"})
# Job states in which another process may be writing the same checkpoint.
BUSY_JOB_STATES = frozenset({"running", "preparing"})

UNRECORDED = "unrecorded"


@dataclass(frozen=True)
class FallbackEntry:
    """One chunk that fell back, as the job progress records it."""

    href: str
    index: int
    reason: str
    attempts: Optional[int]
    causes: Tuple[str, ...]
    degraded: bool  # translated, with approximate tag positions


def collect_fallback_entries(progress: Mapping[str, Any]) -> List[FallbackEntry]:
    """Every flagged chunk of a job, sorted by file and chunk index.

    A chunk listed only in ``epub_degraded_units`` (a job written before the
    reasons were recorded) is kept with reason "unrecorded" so the repair still
    covers it.
    """
    degraded: Dict[str, set] = {
        str(href): {int(index) for index in indices or []}
        for href, indices in (progress.get("epub_degraded_units") or {}).items()
    }
    entries: Dict[Tuple[str, int], FallbackEntry] = {}
    for href, records in (progress.get("epub_fallback_units") or {}).items():
        for key, record in (records or {}).items():
            index = int(key)
            entries[(str(href), index)] = FallbackEntry(
                href=str(href),
                index=index,
                reason=str(record.get("reason") or UNRECORDED),
                attempts=record.get("attempts"),
                causes=tuple(record.get("causes") or ()),
                degraded=index in degraded.get(str(href), set()),
            )
    for href, indices in degraded.items():
        for index in indices:
            entries.setdefault(
                (href, index),
                FallbackEntry(href, index, UNRECORDED, None, (), degraded=True),
            )
    return [entries[key] for key in sorted(entries)]


def summarize_fallbacks(entries: Sequence[FallbackEntry]) -> Dict[str, Any]:
    """Counts by reason and by file, for the dry-run report."""
    by_reason: Dict[str, int] = {}
    by_file: Dict[str, int] = {}
    for entry in entries:
        by_reason[entry.reason] = by_reason.get(entry.reason, 0) + 1
        by_file[entry.href] = by_file.get(entry.href, 0) + 1
    return {
        "chunks": len(entries),
        "files": len(by_file),
        "by_reason": dict(sorted(by_reason.items())),
        "by_file": dict(sorted(by_file.items())),
    }


def repair_refusal(book_status: str, job_state: str) -> Optional[str]:
    """Why the repair must not run now, or None when it may run."""
    if book_status not in REPAIRABLE_BOOK_STATES:
        return (
            f"book is {book_status!r}; the repair runs only on "
            f"{' or '.join(sorted(REPAIRABLE_BOOK_STATES))} books"
        )
    if job_state in BUSY_JOB_STATES:
        return f"job is {job_state!r}; wait until it stops before repairing"
    return None


def repair_command(base_command: Sequence[str]) -> List[str]:
    """The normal translation command, asked to retry the flagged chunks.

    ``base_command`` must already carry ``--translation-id`` so the run resumes
    the book's checkpoint instead of starting a new one.
    """
    return [*base_command, "--retry-token-aligned"]


def run_repair(
    base_command: Sequence[str],
    *,
    runner: Callable[..., Any],
    cwd: Any,
) -> int:
    """Run the repair command and return its exit code."""
    completed = runner(repair_command(base_command), cwd=cwd, check=False)
    return int(completed.returncode)
