# Concurrency baseline — literary queue API (2026-11-11)

Baseline for prompt 5.3: the production-shaped failure mode, measured before the
single-writer refactor. The harness is `tests/standalone/concurrency_baseline.py`
with the independent writer `tests/standalone/concurrency_writer.py`. It never
opens the live `data/literary_queue.db`: the scratch database lives in
`data/tmp/concurrency-baseline-<stamp>/`, which is git-ignored, and the writer runs
inside the app container through the same `/app/data` bind mount the runner uses.

## Run 2026-11-11T20:29:25Z (the run that reports this baseline)

| Metric | Value |
| --- | ---: |
| Operations (approve/retry/add/move/remove) | 100 |
| 2xx | 62 |
| 409 expected conflict | 4 |
| 404 race not found | 10 |
| 500 | 24 |
| API failure rate (5xx) | 24.00% |
| `database is locked` in the server log | 0 |
| Timeouts >= 29 s | 0 |
| Max / p95 elapsed | 1.49 s / 0.509 s |
| Writer iterations | 45 |
| Writer lock errors | 0 |
| Writer disk I/O errors | 49 |

Probes (same run)

| Probe | Result |
| --- | --- |
| `host_hold` (host holds a write transaction) | 4 of 5 API calls failed; max 30.249 s; integrity `ok` |
| `container_hold` (container holds a write transaction) | 0 of 5 failed; 4 writes succeeded during the hold; integrity `wrong # of entries in index idx_jobs_book` |

End state of the scratch database: `error: database disk image is malformed`,
one state-read inconsistency, the translating book reported not alive.

## Earlier runs

- `20260111T200322Z` (run 2026-11-11T20:03:22Z, reported by the earlier OpenCode
  session): 100 operations, 73 of them 500, 25 writer disk I/O errors, 0 lock errors.
- `20261111T200018Z`: 5 operations only (smoke test), 0 failures.

## What the baseline says

- The failures are not `database is locked` at the application level. They are
  disk I/O failures and index corruption on the bind-mounted queue database,
  plus a 30 s stall when a host-side write transaction is held.
- Failure rate varies between runs (24% and 73%). The single-writer target is
  zero 5xx, zero stalls and an `ok` integrity check after the same 100 operations.
- The run did not touch the live queue; the live translation (Kingdoms of Death)
  was running during the baseline.

Raw artefacts (git-ignored): `data/tmp/concurrency-baseline-20261111T202924Z/`
(`report.md`, `report.json`, `ops.jsonl`, `server.log`, writer logs).
