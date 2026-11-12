# Write map for `literary_queue.db` (prompt 5.1, 2026-11-12)

Read-only. Sources: `src/literary/queue.py` (QueueStore), `src/literary/queue_intents.py`
(spool and apply), `src/api/blueprints/literary_queue_routes.py`, `src/literary/cli.py`,
`scripts/queue_runner_agent.py`, `scripts/auto_queue.py`.

## Who writes, and how

| Writer | Path | Transaction and timeout | Journal | Notes |
| --- | --- | --- | --- | --- |
| Queue agent (`queue_runner_agent.py`) | `_apply_intents` → `queue_intents.drain` → `_apply_*` handlers (`add`, `approve`, `retry`, `move`, `remove`, `update_model`, `event`) | `isolation_level=None` (autocommit), `busy_timeout` 30 s | DELETE (rollback) | the intended single writer for UI changes |
| CLI and in-process runner (`cli.py`, `queue_runner.py`) | `QueueStore` methods (`add_book`, `set_book_state`, `set_job_state`, `mark_reviewed`, `remove_book`, `move_book`, `create_job`, progress and chapter upserts, `pause`) | `with self._connect()` (implicit transaction), `sqlite3.connect(timeout=30)` | DELETE (`PRAGMA journal_mode = DELETE`) | runs the translation; writes per chunk |
| Auto supervisor (`auto_queue.py`) | calls the CLI in a subprocess (`queue approve`, `queue run`) | same as the CLI | DELETE | it does not write the DB directly |
| Flask routes (`literary_queue_routes.py`) | `queue_intents.enqueue` at lines 595, 700, 735, 800, 821, 872, 897 (add, PATCH, move, approve, retry, remove, model) | writes a spool file, not the DB | n/a | read paths use `mode=ro` connections (lines 124-495) |
| Flask control and run routes | `control.json` (line 542) and `run-request.json` (line 574) | file writes | n/a | not the DB |

## Concurrency and corruption risk

- **Rollback journal on a shared bind mount.** The database lives on a Windows bind
  mount that the app container also reads. WAL is not used because the container cannot
  open the `-shm` file. Readers and writers therefore block each other during commits.
- **Timeouts.** Writers wait 30 s on a busy database and then fail. The per-chunk
  progress writes are the most frequent writers, so they are the first to hit a lock.
- **No compare-and-set.** Status updates are plain `UPDATE books SET status = ?`. Two
  writers that act on the same book at the same time: the last one wins.
- **Autocommit in the agent.** The intent handlers run in autocommit. A crash in the middle
  of one handler can leave a partial change; the code does not show an explicit `BEGIN`
  around each handler (not verified in every handler).

## Risk classes

| Write | Class | Why |
| --- | --- | --- |
| `DELETE FROM books` (`remove_book`, `_apply_remove`) | high | Removes a book row. The agent path refuses active states (`_apply_remove`, `ACTIVE_STATES`). The CLI method `QueueStore.remove_book` has no such check. |
| `set_book_state` / `set_job_state` / `mark_reviewed` | high | The state machine. Two writers (CLI run, agent intents, supervisor's CLI calls) can overwrite each other. |
| `pause` (UPDATE ... WHERE status IN active states) | medium | Filters on active states, but a book finishing at the same moment can race with it. |
| progress and chapter upserts (`jobs.current_chapter`, `chapters`) | medium | Frequent; a lock timeout loses progress, not the result. |
| `add_book` (INSERT ... ON CONFLICT DO UPDATE) | low | Idempotent for the same source and config hash. |
| `events` inserts | low | Append only. |

## The three most dangerous points

1. **`QueueStore.remove_book` with no active-state guard** (`queue.py:488-504`). A caller
   that is not the agent can delete the row of a running book; the job and chapters cascade.
   The agent path is protected; the CLI path is not. The callers were not checked in this pass.
2. **Unguarded status writes from more than one writer** (`set_book_state`, `set_job_state`,
   `mark_reviewed`). The intent to approve and the in-process runner can write the same book.
   The fix is a compare-and-set (`WHERE status = ?`) and a single writer for all state changes.
3. **Rollback journal across the bind mount, with 30 s timeouts.** Under contention, a write
   during a run fails with "database is locked" and the run may stop mid-chunk. Recovery
   is by checkpoint, but it is a manual step (see the destructive tests).
