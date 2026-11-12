# 24 h destructive window: runbook (prompt 4.4)

Status: **prepared, not run.** The preflight, the dedicated compose file and the short
mode are ready. The window phases (pause/resume on the dedicated app, app restart mid-run,
queue DB corruption on the scratch copy, the 24 h soak) are **not implemented yet**;
`--mode window` refuses to run. Write them before the window.

Why the window is needed: the container-kill test stops the app container, and a
translation running in it stops with it (exit 137). The live queue must be idle first.

## Before the window

1. Run the read-only preflight. It must exit `0`:

   ```bash
   python tests/standalone/destructive_24h.py --preflight
   ```

   Exit `3` means the live stack is busy (an active book, `runner.json` running, or a
   `translate.py` process in `translatebook-literary-dev`). Do not start the window.
2. Close the queue agent window (`start-queue-agent.bat`) so that no run starts during
   the window. The auto supervisor must not be running either.
3. Back up the live queue database into the scratch area, not in place:

   ```bash
   mkdir -p data/tmp/destructive-window/backup
   cp data/literary_queue.db data/tmp/destructive-window/backup/
   ```

4. Check the disk space for the scratch area and the soak output.
5. If the soak uses the real model, confirm that the host Ollama is free of other work.

## Steps

**A. Short mode (safe only when the preflight is ready).**

```bash
python tests/standalone/destructive_24h.py --mode short
```

It runs the corrupt-copy recovery, a kill and resume of a scratch translation, the
duplicate-output probe and the pause-control transition. It never touches the live queue
database. `--app-restart` is refused in short mode.

**B. Window mode, on the dedicated instance.**

1. Put a scratch copy of the queue database where the dedicated instance reads it:

   ```bash
   mkdir -p data/tmp/destructive-window/data
   cp data/tmp/destructive-window/backup/literary_queue.db data/tmp/destructive-window/data/
   ```

2. Start the dedicated app (port 5056, its own container and volumes):

   ```bash
   docker compose -f docker-compose.destructive.yml up -d app-destructive
   curl -f http://127.0.0.1:5056/api/health
   ```

3. Run the window phases (to be written): queue-level pause and resume with a real
   translation; app restart mid-translation on `app-destructive`; corruption of the scratch
   queue database (not the live one); resume with the target EPUB already present.
4. The 24 h soak: one real translation of a copy of a book, for 24 hours, with the real model.
   Set `DESTRUCTIVE_OLLAMA_ENDPOINT` if the endpoint differs from the default.

**Criteria** (all must hold):

- no book advances state without a checkpoint;
- no duplicate output with a `(1)` suffix;
- no job left in `translating` after its book completes.

**C. After the window.**

```bash
docker compose -f docker-compose.destructive.yml down
```

Use `down -v` only to drop the scratch volume. Keep the report under
`data/tmp/destructive-24h-<stamp>/`, then delete the scratch copies. Start the queue agent
again.

## Not verified

- The dedicated compose file was validated with `docker compose config` only; it has not
  been started.
- The window phases and the soak are not written, so this runbook cannot be completed yet.

## Criteria check (read-only, usable any time)

```bash
python tests/standalone/destructive_24h.py --evaluate data/tmp/destructive-window/data/literary_queue.db \
    --outputs data/tmp/destructive-window/outputs
```

It reads the queue database (read-only) and the outputs folder, and prints the three
criteria with the details of any failure. Exit `0` means all three hold. It is used on the
scratch database, not on the live one.
