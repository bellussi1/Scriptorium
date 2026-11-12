# Single writer for `literary_queue.db` — design (2026-11-11)

Design for prompt 5.2, implemented under prompt 5.4 on branch
`claude/epic-matsumoto-f4f45f`. Not merged. Written while the Kingdoms of Death
run was active; nothing here is deployed to the running app container.

## 1. Problem

The 5.3 baseline (numbers in the table below)
measured 24% 5xx on the 100-operation run (73% on an earlier run), a
`database disk image is malformed` end state, index inconsistencies, and a
30.2 s stall while a host process held a write transaction.

The failure is not application-level `database is locked`. Two writers on
opposite sides of the Docker bind mount write the same SQLite file. The
`container_hold` probe showed that a write transaction held inside the
container did not block host writes (4 of 4 succeeded) and left
`wrong # of entries in index idx_jobs_book`. SQLite's file locks do not
coordinate across the Windows/9p boundary, so journal `DELETE` does not make
two such writers safe.

## 2. Topology (checked in code)

| Writer | Runs in | Writes `literary_queue.db` | Source |
| --- | --- | --- | --- |
| Flask routes (approve, retry, add, move, remove, PATCH model, `POST /run` event) | app container | directly, over the `./data` bind mount | `src/api/blueprints/literary_queue_routes.py` |
| `queue run-all` (host runner) | Windows host, started by the agent | directly, on NTFS; reads `data/jobs.mirror.db` | `src/literary/queue_runner.py`, `scripts/queue_runner_agent.py` |
| Translation | app container, under `docker compose exec` owned by run-all | no; writes `jobs.db` on the `jobs_state` volume (ext4) | `docker-compose.dev.yml`, `src/persistence/mirror.py` |
| CLI (`src.literary.cli queue ...`) | host | directly, on NTFS | out of scope |

The app is the only writer that crosses the bind mount. Pause and run
requests are JSON files (`queue_control.py`, `queue_run_control.py`), not
SQLite, and stay as they are.

## 3. Decision

- The app never writes SQLite. A mutation becomes one spool file in
  `<db-stem>.intents/` (for production, `data/literary_queue.intents/`),
  written with temp file plus `os.replace`, the same pattern as the run
  request file that already works across the mount.
- The host runner, `src/literary/queue_intents.py::drain()`, ingests spool
  files into the table `queue_intents` in id order, then applies pending rows
  in id order, one transaction per intent. It runs in the agent loop and can
  be run directly with `python -m src.literary.queue_intents`.
- The UI reads results from the table through
  `GET /api/literary/queue/intents/<token>`.

Deviation from the 5.2 wording: the app does not insert rows into the table.
Doing so would make the app a second writer across the bind mount, which is
the failure above. The table is still the durable intent log and the only
source of results.

## 4. Schema

```sql
CREATE TABLE IF NOT EXISTS queue_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- apply order
    token TEXT NOT NULL UNIQUE,            -- client id; spool file name suffix
    kind TEXT NOT NULL,                    -- add | approve | retry | move | remove | update_model | event
    payload TEXT NOT NULL DEFAULT '{}',    -- JSON; facts only the app can see are computed at enqueue
    created_at TEXT NOT NULL,              -- UTC ISO-8601, set by the app
    applied_at TEXT NOT NULL DEFAULT '',   -- empty while pending; set when applied or refused
    error TEXT NOT NULL DEFAULT '',        -- refusal message, empty on success
    error_status INTEGER NOT NULL DEFAULT 0, -- HTTP status for a refusal (400/404/409)
    result TEXT NOT NULL DEFAULT '{}'      -- JSON outcome, e.g. new book ids
);
CREATE INDEX IF NOT EXISTS idx_queue_intents_pending
    ON queue_intents(applied_at, id);
```

## 5. Migration

- Additive only. `ensure_schema()` runs the statements above on every drain.
  No existing table, row or index changes. The existing `QueueStore` ignores
  the table.
- The app treats a missing table as "nothing applied yet" and reads pending
  work from the spool.
- Connections are opened with `timeout=30` and `PRAGMA busy_timeout=30000`,
  `foreign_keys=ON`, and `journal_mode=DELETE`, as in `QueueStore`. The app's
  read connections keep `mode=ro`.
- Rollback: stop the runner, restore the previous routes, optionally
  `DROP TABLE queue_intents`. Nothing else references the table. Spool files
  left behind are ignored by the old code.

## 6. Intent kinds

Payloads are built by the app from its own view (container paths, file
hashes, the live checkpoint DB). Apply-time checks repeat the rules the routes
used to enforce.

| Kind | Enqueued by | Payload | Refused at apply time when | Result |
| --- | --- | --- | --- | --- |
| `add` | `POST /books` | `books[]` (BookRecord fields, container `epub_path`, `source_hash`, `config_hash`), `target_language`, `model`, `provider` | never; books already queued are reported as duplicates | `added[]`, `duplicates[]` |
| `approve` | `POST /books/<id>/approve` | `book_id` | not `needs_review` and already reviewed (409); book missing (404) | — |
| `retry` | `POST /books/<id>/retry` | `book_id`, `release_stale_checkpoint` | not failed/needs_review/paused (409); job active (409) | — |
| `move` | `POST /books/<id>/move` | `book_id`, `direction` | not pending (409); already at edge (409); missing (404) | `moved{book_id, direction}` |
| `remove` | `DELETE /books/<id>` | `book_id` | job or book active (409); missing (404) | `removed{book_id, title}` |
| `update_model` | `PATCH /books/<id>` | `book_id`, `model`, `provider` | not pending (409); missing (404) | `updated{book_id, model, provider}` |
| `event` | `POST /run` | `message`, `book_id` | never | — |

`release_stale_checkpoint` is decided at enqueue, because only the app can
read the live `jobs.db` on the ext4 volume. The job cannot be active at that
moment: the route checks it, and apply checks it again.

`remove` also detaches the book's history: its events get `book_id` NULL
before the row is deleted, so no event refers to a deleted book. The removal
event itself is written with a NULL `book_id`, as before. The CLI path
(`QueueStore.remove_book`) still leaves those references; changing it means
editing `queue.py`, which the running translation loads, so it waits.

Apply rules:

- Strict id order. A transient lock (`database is locked`) stops the batch;
  nothing is skipped.
- One transaction per intent. Effects, `applied_at`, `error`, `error_status`
  and `result` commit together. A crash rolls back and the intent is applied
  again, in order.
- Idempotent. Rows with `applied_at` set are never applied again. Ingest is
  `INSERT OR IGNORE` on `token`, and a spool file is deleted only after its
  ingest commit, so a re-ingested file is a no-op.
- A refusal is recorded (`applied_at`, `error`, `error_status`) and does not
  block later intents.
- An unexpected exception is recorded as `internal error: ...` and the
  traceback goes to the log. A bad payload cannot stall the queue.
- A malformed spool file becomes a refused intent with an explanatory error.

## 7. When the runner is stopped

- The app still accepts requests, writes spool files and returns `202` with
  the token and the current snapshot. The UI shows the change as queued.
  (The runner drains with `python -m src.literary.queue_intents --db <db>
  --once`; the agent calls the same `drain()` every 0.5 s.)
- Nothing is applied. The snapshot reports `intents.pending` and the age of
  the oldest pending intent. `agent.online` already shows whether the runner
  is alive.
- The backlog survives agent and container restarts: spool files on the bind
  mount, rows in the table. On start the runner drains in order.
- Behaviour change: approve, retry, move, remove, add and model changes take
  effect only while the host agent (or `queue intents drain`) runs. Before,
  they worked without it. `AGENTS.md` already says the queue needs the agent,
  so this matches the operating model, but the UI must say "waiting for the
  runner" instead of looking broken.
- Spool and applied rows are not pruned in this change. Pruning is a
  follow-up.

## 8. UI compatibility

- Same paths, methods and status codes whenever the runner applies within
  `LITERARY_INTENT_WAIT_S` (default 2.5 s). The route polls the table and
  returns the same bodies as before: the snapshot plus `added`, `duplicates`,
  `not_found`, `moved`, `removed`, `updated`, as applicable.
- Refusals detected at enqueue still return `404`, `409` or `400` at once.
- A refusal recorded at apply time returns its recorded `error_status` when the
  runner is fast enough.
- Otherwise the route returns `202 Accepted` with
  `intent: {token, kind, state: "queued"}` and the snapshot. The UI polls
  `GET /api/literary/queue/intents/<token>` until `state` is `applied`, then
  refreshes. A refusal is shown as the same error text as before.
- `POST /api/literary/queue/run` keeps its `202` and body. Its event is an
  intent.
- Deployment order matters. The agent must run the new drain before the app
  sends intents; otherwise they wait. The new UI handles `202` by polling.

## 9. Reads still cross the bind mount (open risk)

The app reads `literary_queue.db` through `mode=ro` connections over the same
bind mount, and those reads are not lock-coordinated with host writes either.
This change removes the app's writes, not its reads. The 5.3 baseline does not
isolate read errors, and the harness serves the API from the host, so the
container read path is not exercised. The follow-up is to serve UI reads from
a host-written mirror, as `jobs.mirror.db` already does for checkpoints.

## 10. Out of scope

- CLI writes, the runner's own writes (sync, chapters, events), and the
  translation's writes to `jobs.db`. All are host-side or on ext4.
- The pause control file and the run request file.
- Container-side reads (section 9).

## 11. Verification plan

- Harness: applier and writer run on the host, which matches production
  (section 2). 100 operations. Expect 0 5xx, 0 lock errors, 0 stalls and an
  `ok` integrity check on the scratch database.
- Probe `host_hold` re-run: API calls should not fail while the host holds a
  write transaction, because they only write spool files.
- Probe `container_hold` is not re-run. It needs the main compose project and a
  container that is busy with the live run. The 5.3 result stands.
- `pytest -q tests/unit tests/literary`.
- Not verified here: the app container image and runtime path, the Windows
  agent with a real run, and the UI in the Docker app.

## 12. Rollout

1. After the Kingdoms of Death run ends (`queue status --json`: `running` false).
2. Merge; restart `start-queue-agent.bat` so the agent drains intents.
3. Restart the app container so the new routes load
   (`docker compose -f docker-compose.dev.yml up -d --build app`, only when no
   translation is running). The image rebuild is needed only if Dockerfile
   inputs changed; `src` is bind-mounted.
4. Check the Queue tab and `queue status --json`.

Rollback: revert the merge, restart the agent, restart the app.

## 13. Owner decisions

- Accept that queue changes need the host agent running.
- Accept the spool-file deviation from the 5.2 wording (section 3).
- Decide whether UI reads move to a host-written mirror (section 9), now or
  later.

## 14. Verification results (2026-11-11, branch only)

Stress run: `python tests/standalone/concurrency_baseline.py --skip-9p`
(writer on the host, applier on the host; scratch DB under `data/tmp/`).

| Metric | Baseline (5.3, container writer) | This change |
| --- | ---: | ---: |
| 500 responses | 24 (24%) | 0 |
| `database is locked` / lock errors | 0 / 0 | 0 / 0 |
| Timeouts >= 29 s | 0 | 0 |
| Max / p95 elapsed | 1.49 s / 0.509 s | 0.633 s / 0.551 s |
| 2xx / 409 / 404 | 62 / 4 / 10 | 87 / 7 / 6 |
| Intents applied / refused / failed / pending | — | 87 / 2 / 0 / 0 |
| Writer lock errors / disk I/O errors | 0 / 49 | 0 / 0 |
| Integrity / inconsistencies | `malformed` / 1 | `ok` / 0 |
| Probe `host_hold`: failures, max elapsed | 4 of 5, 30.249 s | 0 of 5, 2.611 s |

The two intent refusals were expected races (`404 book not found`, and a
retry of a book that was no longer retryable); they came back through the
applied result. The other 409 and 404 responses were enqueue-time checks, so
no intent was written for them. No request returned `202`: every accepted
change was applied inside the 2.5 s wait.

`pytest -q tests/unit tests/literary`: 2430 passed, 6 skipped, 0 failed.

Not verified in this change:

- The live app container still serves the main checkout. Rebuilding or
  restarting it would stop the Kingdoms of Death run, so the new routes and
  the Queue UI were not exercised in the running app.
- The UI in a browser: the 202 polling in `queue-manager.js`, and the language
  toggle smoke test that `CLAUDE.md` requires for new strings. `node --check`
  and the JSON parse passed; nothing else.
- The container read path (reads over the bind mount while the host writes).
- The `container_hold` probe: not re-run. The 5.3 result stands as the
  evidence for the cross-boundary writer.
- The agent loop with a real run: the drain is wired in, but the live agent
  was not restarted.
