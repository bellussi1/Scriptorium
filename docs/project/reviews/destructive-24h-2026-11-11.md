# Destructive 24 h — rehearsal and window plan (2026-11-11)

Scope: a short, isolated rehearsal of the 24 h destructive plan. The rehearsal
used a scratch jobs DB, a synthetic EPUB, the mock Ollama model and the app
container's `translate.py`. It did not touch the live queue DB, the live jobs
DB or a real book. The full 24 h run still needs a maintenance window.

## Short run

Command:

```bash
python tests/standalone/destructive_24h.py --mode short --app-restart
```

Work dir: `data/tmp/destructive-24h-20261111T191250Z`.
Duration: 51 s.

| Phase | Result | Evidence |
| --- | --- | --- |
| DB recovery on copies | PASS | 5/5 scenarios; `destructive-recovery-20261111T191252Z/summary.json` |
| CLI kill at chunk 2/6, then resume | FAIL | checkpoint 2/6, 3 checkpoint rows, resume exit 0, output written, job still `running` |
| CLI resume with the target EPUB already present | FAIL | `Destructive-24h-20261111T191250Z (1).epub` created next to the original |
| Pause control (file-level) | PASS | `pause_now` requested, honored for book 1, cleared |
| App restart (idle) | PASS | healthy in 7.3 s |

Criteria:

| Criterion | Result | Evidence |
| --- | --- | --- |
| No job advances state without a checkpoint (CLI path) | PASS | 2 completed chunks, 3 checkpoint rows before the resume |
| No duplicate file with `(1)` | FAIL | third pass wrote `… (1).epub` |
| No job stuck in `running` after completion | FAIL | `translation_jobs.status = running` after 6/6 and after the second resume |

The short run does not exercise the queue-level book state; that check belongs
to the 24 h window, where the queue DB is the source of truth.

## Open failures

1. **Duplicate output on resume.** The third pass started with
   `Destructive-24h-20261111T191250Z.epub` already on disk and wrote
   `Destructive-24h-20261111T191250Z (1).epub`. Root cause is the output-path
   handling: a resumed job should reuse or replace its partial target instead
   of `get_unique_output_path` creating a `(1)` sibling. This is the same
   finding as `DESTRUCTIVE_TESTS.md`; it is still open.
2. **Upstream status stays `running`.** The scratch
   `translation_jobs.status` was `running` after the resumed CLI finished with
   6/6 chunks. The queue runner marks the queue job `needs_review` after the
   process, so the queue flow is protected, but the direct CLI and the
   upstream status are wrong. The 24 h acceptance fails on this criterion
   until the CLI completion path marks the job completed.

Both failures are in the CLI path. The short run did not exercise the queue
runner; the queue-level pause/resume and the app restart mid-translation are
window items below.

## What passed safely

- Corrupt jobs DB with a healthy snapshot: restored, corrupt copy preserved.
- Corrupt newest snapshot: skipped in favor of the older healthy one.
- Corrupt without snapshot: fail closed, file kept.
- Truncated live DB: restored.
- Pause-now control: request, honor, clear and book id recorded.
- App restart with no active translation: healthy in 7.3 s.
- The killed process did not advance the job to `completed`; the checkpoint
  rows were present before the resume.

## 24 h window plan

### Prerequisite

The queue runner hardcodes `docker-compose.dev.yml` and the `app` service in
`src/literary/queue_runner.py` (translation, kill and process-list commands).
The 24 h run needs a dedicated app instance, so the compose file and service
must become configurable (for example `LITERARY_COMPOSE_FILE` and
`LITERARY_APP_SERVICE`) before the window. This is a code change, not a test
step. Without it, the queue path cannot use the scratch DB without touching
the live app.

Dedicated instance:

- `docker-compose.destructive.yml` with an `app-destructive` service on
  `127.0.0.1:5002`;
- `JOBS_DB_PATH=/app/state-destructive/jobs.db` on a separate named volume;
- `LITERARY_QUEUE_DB=/app/data/tmp/destructive-24h/queue.db`;
- a separate `translated_files_destructive` mount;
- the same image and the local model endpoint;
- the host queue runner pointed at this compose file and service.

### Schedule

| Time | Phase | Check |
| --- | --- | --- |
| T+0 | Baseline: dedicated app healthy, scratch queue/jobs DB, 30-chapter synthetic EPUB or a book the owner authorizes | one book at a time, DB integrity ok |
| T+0–2 h | Clean run from `pending` to `needs_review` | checkpoints at 25/50/75/100%, no state before a checkpoint |
| T+2 h | SIGKILL at 30%, inspect, resume | resume index equals the last checkpoint; no `(1)`; no `running` after completion |
| T+4 h | Corrupt the scratch jobs DB, restore from snapshot, resume | restore ok, no lost chunks, no duplicate |
| T+6 h | Pause-now at 50%, inspect, resume | book `paused`, no next book, resume from the checkpoint |
| T+8 h | Restart the dedicated app mid-run | healthy < 1 min, queue-owned job skipped in startup restore, resume continues |
| T+10 h | Pre-create the target EPUB, resume | no `(1)` file, audited artifact hash unchanged |
| T+12–22 h | Repeat kill/restart/pause cycles every 2 h | all three criteria every cycle |
| T+24 h | Final report and cleanup | no live DB or book touched |

### Acceptance

1. Every `completed` book has a checkpoint covering all chunks; every
   `translating` book has an active job and at least one checkpoint.
2. No `<name> (1).epub` in the test output directory.
3. No `translation_jobs.status = running` after the process exits and the
   queue job is `needs_review` or `completed`.
4. App healthy in under one minute after each restart.
5. One book at a time; no second runner while one is active.
6. The audit target hash matches the reviewed artifact.

### Stop conditions

Stop the run and keep the evidence on the first violation of any acceptance
criterion, on two consecutive restart-budget halts, on an app unhealthy for
more than two minutes, or on any live-DB write. Do not clean the work dir
before the report is written.

### Window requirements

- 24 h of dedicated app and GPU time; no live translation during the window.
- The dedicated compose instance and the configurable queue-runner target.
- The two open CLI fixes (duplicate output, stuck `running`) if the run is
  meant to pass; otherwise the run will fail on the known defects by design.
- Owner authorization for the synthetic-vs-real book choice and the model
  spend (local Index, no cloud).

## Files

- Harness: `tests/standalone/destructive_24h.py`.
- Short-run report: `data/tmp/destructive-24h-20261111T191250Z/report.json`
  and `report.md`; logs `pass1.log`, `pass2.log`, `pass3.log`.
- Existing recovery harness: `tests/standalone/destructive_recovery.py`.
- Existing findings: `docs/project/DESTRUCTIVE_TESTS.md`.
