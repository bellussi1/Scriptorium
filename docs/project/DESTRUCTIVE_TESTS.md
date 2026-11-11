# Destructive reliability tests

Date: 2026-11-11. Scope: prove that a corrupt jobs DB and a hard kill of the
translation process or the app container do not lose committed chunks and that
the next run resumes from the checkpoint. The live queue, the live jobs DB and
Howling Dark / Demon in White were not touched.

## Safety model

- The jobs DB tests use **copies** under `data/tmp/destructive-recovery-*`;
  `recover_live_db_if_needed` is pointed at the copy and a copy-only backup
  directory.
- The translation kill tests use a **scratch jobs DB** under `data/tmp/`, a
  synthetic 3-chapter EPUB and a unique translation id/output, never the live
  `JOBS_DB_PATH` or the queue DB.
- The model is a deterministic local mock of the Ollama chat API
  (`/api/chat` streaming, `/api/show`, `/api/tags`) so the tests do not compete
  with Demon in White's refine for the GPU. The mock exercises the checkpoint
  plumbing, not translation quality; the real model resume was already proven by
  Howling Dark's production resume from index 32.
- The container kill test restarts the app immediately and verifies the health
  endpoint. The host-side Demon refine is not in the container and keeps
  running.

## Test 1 — corrupt a copy of jobs.db

Script: `tests/standalone/destructive_recovery.py`.

| Scenario | Result |
| --- | --- |
| Healthy live DB | `ok`, no restore, no corrupt copy |
| Corrupt live + one healthy snapshot | `restored`, integrity `ok`, corrupt copy kept |
| Corrupt live + no snapshot | `corrupt`, file kept, corrupt copy kept (fail closed) |
| Corrupt newest snapshot + healthy older one | `restored` from the older snapshot; the bad one skipped |
| Truncated live + healthy snapshot | `restored`, integrity `ok` |

Five of five passed. Evidence:
`data/tmp/destructive-recovery-20261111T141220Z/summary.json`.

## Test 2 — kill the translation process mid-chunk

- Synthetic EPUB: 3 chapters, 6 chunks.
- Scratch DB: `data/tmp/killtest-20261111T1418/jobs.db`.
- Translation id: `cli_killtest_1418`.
- After the first checkpoints, the process was killed with SIGKILL through
  `src.literary.kill_translation` (PID 13958). `find_pids` returned empty.
- State at the kill: progress `completed_chunks=2/6`, one file row (`ch1`).
- Resume log: `Resuming cli_killtest_1418 from checkpoint index 1`.
- Final state: `completed_chunks=6/6`, three file rows, output EPUB written.
- Observation: the resumed run wrote `Destructive-Killtest-1418 (1).epub`
  because the target file already existed from pass 1. This is a real edge
  case: a resume should reuse or replace the partial output instead of
  creating a `(1)` duplicate. The queue path usually kills before the final
  EPUB exists, but a failure after the EPUB write could hit it.

Logs: `data/tmp/killtest-20261111T1418/pass1.log`, `pass2b.log`.

## Test 3 — kill the app container mid-translation

- Scratch DB: `data/tmp/killcontainer-20261111T1420/jobs.db`.
- Translation id: `cli_killcontainer_1420`.
- After the first checkpoints (`completed_chunks=2/6`), the app container was
  killed with `docker compose kill app` (SIGKILL).
- The app was restarted with `docker compose up -d app` and reached `healthy`
  in under a minute; the startup log found the live incomplete jobs and left
  them to the queue.
- Resume log: `Resuming cli_killcontainer_1420 from checkpoint index 1`.
- Final state: `completed_chunks=6/6`, three file rows, output
  `Destructive-Killcontainer-1420.epub` written (2,968 bytes).
- The host-side Demon refine process kept running across the container kill.

Logs: `data/tmp/killcontainer-20261111T1420/pass1.log`, `pass2.log`.

## Findings

1. **Recovery is safe.** The corrupt/truncated DB is never overwritten without
   a preserved copy; a bad snapshot is skipped; no healthy snapshot fails
   closed.
2. **Checkpoint resume survives SIGKILL and container death.** The runner does
   not lose committed chunks and the resume index comes from the reconciled
   rows, not the possibly stale progress JSON.
3. **Duplicate output on resume.** Fix the output-path handling so a resumed
   job reuses its partial target instead of `get_unique_output_path` creating a
   `(1)` file. Queue impact is low; direct CLI impact is visible.
4. **Upstream status stays `running`** after a resumed CLI finishes with every
   chunk already done (the queue runner still marks `needs_review` after the
   process, so the queue flow is unaffected). Worth a small fix in the CLI
   completion path.

## Reproduction

```bash
python tests/standalone/destructive_recovery.py

# Start the mock (host) and use a scratch jobs DB:
python tests/standalone/mock_ollama.py   # MOCK_DELAY=1.5 for a kill window
python tests/standalone/build_destructive_epub.py data/tmp/killtest/test.epub
docker compose -f docker-compose.dev.yml exec -T \
  -e JOBS_DB_PATH=/app/data/tmp/killtest/jobs.db \
  -e OLLAMA_API_ENDPOINT=http://host.docker.internal:11555/api/generate \
  -e OLLAMA_NUM_CTX=4096 app \
  python translate.py -i /app/data/tmp/killtest/test.epub \
  -o /app/translated_files/Destructive-Killtest.epub \
  -sl English -tl "Portuguese (Brazil)" --provider ollama -m mock \
  --no-color --translation-id cli_killtest
# Then kill with src.literary.kill_translation or `docker compose kill app`,
# restart the container, and repeat the same command with --translation-id.
```
