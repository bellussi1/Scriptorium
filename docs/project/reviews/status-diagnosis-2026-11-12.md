# Status diagnosis and supervisor map (prompts 2.1 and 2.4, 2026-11-12)

Read-only. Sources: `.opencode/plugins/literary-context/index.ts` (modified 2026-11-11
12:59), the `data/literary_queue.*.json` files, `python -m src.literary.cli queue status
--json`, and the code that reads and writes each file. Nothing was edited.

## 2.1 Diagnosis: "next #11 Kingdoms" while Demon in White was translating

**What the data says.** `next` is not "running". The canonical status computes it as the
first book with `status = 'pending'`, ordered by `priority DESC, series, series_index, id`
(`src/literary/queue.py:916`, `src/api/blueprints/literary_queue_routes.py:491`). A book in
`translating`, `needs_review` or `completed` is never `next`. So while Demon in White
(priority 999999) was translating, Kingdoms of Death (priority 999998, still `pending`) was
the correct next pending book. The database was not lying at that moment.

**What was wrong.** The plugin mixed three different clocks in one block:

1. The injected block is text written when the session starts. It does not refresh, so
   `next` could describe a moment hours earlier than `running`.
2. When the live call fails, the plugin reports the last in-memory snapshot
   (`lastStatus`, `index.ts:128-170`). The age is shown, but the block still reads like a
   current status, and the in-memory copy lives only as long as the plugin process.
3. `next` is printed as a plain fact, with no label that it is only the next pending book,
   not the next book to start.

**Lineage of the state files (timestamps from 2026-11-12, 14:36 local time when read):**

| File | Writer | Last write | State now |
| --- | --- | --- | --- |
| `literary_queue.db` (books, jobs) | the agent (single writer) and the CLI | live | Disquiet Gods `translating`, Shadows pending, Kingdoms and Ashes `completed` |
| `literary_queue.runner.json` | run path in `src/literary/queue_run_control.py` | 09:42 | Disquiet Gods, runner pid 11824 |
| `literary_queue.agent.json` | `scripts/queue_runner_agent.py` (`_publish`) | 14:36 (heartbeat) | running; last result Ashes, exit 0 |
| `literary_queue.health.json` | `scripts/watch_translation.py` | 14:36 | active, queue integrity ok |
| `literary_queue.auto.json` | `scripts/auto_queue.py` | 11-11 13:59 | stale: phase `blocked`, Howling Dark |
| `literary_queue.control.json` | pause flags (`queue_control.py`) | 11-11 05:37 | no pause requested |
| `literary_queue.supervisor.json` | `scripts/auto_queue.py` | never written here | absent: the auto supervisor is not running |

**Consumers of that state:** the plugin (`literary_status` tool and the injected block);
the API (`literary_queue_routes.py` builds the queue summary and the `runner` field, and
`translation_routes.py:44` reads the runner); the Queue UI (`queue-manager.js`, through the
API); the supervisors (`auto_queue.py` reads runner and control, `pause_queue_agent.py`
reads runner).

**Where the truth should come from:** the canonical command, read live at query time, with
the database as the only source for book state. Every other file is a cache with an age.
The plugin should show the age of every field, label `next` as "next pending (not started)",
and never show a snapshot without its timestamp.

**Not verified.** I could not reproduce the exact moment of the symptom (the injected block
no longer exists in this session). The diagnosis rests on the code and the current files.

## 2.4 Supervisor and status file map

| Process | Started by | Writes | How often | If it dies |
| --- | --- | --- | --- | --- |
| `scripts/queue_runner_agent.py` | `start-queue-agent.bat` (kept open by the user) | `literary_queue.agent.json`, `literary_queue.runner.json` (through the run path) | heartbeat every 30 s, plus on each request | the Run buttons stop working; a running translation continues until its own exit; nothing restarts the agent |
| `scripts/auto_queue.py` (worker and supervisor) | by hand (`--max-books`, `--interval`) | `literary_queue.auto.json`, `literary_queue.supervisor.json`, `literary_queue.restarts.json` | heartbeat every 30 s; restarts bounded (4.2) | with the restart logic, it restarts a dead worker with backoff; gate holds never restart |
| `scripts/watch_translation.py` | by hand | `literary_queue.health.json` | periodic | health goes stale; the UI shows no health |
| Flask app (`translation_routes`, `literary_queue_routes`) | container start | none of the status files; reads them | per request | the UI shows the last file it can read |
| the CLI `queue run` / `run-all` | the agent, or by hand | DB rows and `runner.json` | per book | the job is left `translating`; `reset_in_progress` makes it resumable on the next start |

**Authoritative:** `literary_queue.db` (book and job state). **Caches:** every `*.json`
file under `data/`. The supervisor file is written only by `auto_queue.py`; it is absent
because that supervisor has not run since 11-11.

**Target design (plan only):** one supervisor process (`queue_runner_agent.py`) that owns
the run, the restarts and the health heartbeat, and one status file produced by
`queue status --json` at read time. What dies: `auto.json` as a separate state, the
separate `runner.json` and `health.json` (their fields move into the status), and the
duplicate run request path once the UI calls the supervisor directly. The auto supervisor
becomes an option of the same process, not a second one.
