# Kingdoms of Death: translation fallbacks (2026-11-11)

Scope: queue book 11, job 24 (`cli_bb4e0e4f`), Index-Translate 9B through Ollama.
Log: `data/queue-runs/kingdoms-of-death.log`. The snapshot below is 1,209 lines,
last chunk 351/862, 18:32 local. The run was still going and kept the code it
started with, so the figures describe that snapshot only.

## Counts in the snapshot

| Log marker | Count | Chunks |
|---|---:|---|
| Placeholder validation failed, fallback used | 3 | 10, 34, 63 |
| Raw response used as fallback | 1 | 10 |
| LLM API request failed | 2 | 10 (attempts 1 and 2) |
| Provider-level errors (HTTP, timeout, JSON, unexpected) | 0 | none |
| Body reconstructed | 31 | 29 with "recovered from N errors" |
| HIGH PLACEHOLDER FAILURE RATE | 2 | 11 and 63 |
| Retry attempt 2/2 | 8 | |

## Findings

1. **The two "API failures" were not API failures.** Both are extraction
   failures of chunk 10. The reply had no translation block, so the translator
   returned None and logged the generic "LLM API request failed". No provider
   exception was raised. The cause was the "Failed to extract translation" line
   printed just before each one.
2. **Fallbacks are not spread across the run.** Four of the first 100 chunks fell
   back (3.8%); none of the next 251 did. Overall: 4 of 351 (1.1%).
3. **The HIGH PLACEHOLDER FAILURE RATE is a per-file sample.** The quality
   counters live in `TranslationMetrics`, which is created per XHTML file. The
   two warnings fired after 5 and 9 processed chunks of a 16- and a 14-chunk
   file. One bad chunk in five is 20 points. The rate did fall to zero, so no
   prompt or sampling change is indicated.
4. **Context overflow at the first chunk** (20:23:27): a 2,258-token request
   against the 2,048-token initial window. The adaptive context retry handled it.
   It is not a fallback.
5. **Text coverage of the reconstructions is unknown for this run.** The old log
   has no coverage figure, and the partial state of the finished files is
   deleted. The new log line reports coverage for every reconstruction.

## Changes

Normal output is unchanged: the prompt, the sampling and the translation path
are the same. The changes are logging, the checkpoint record and the repair.

- `feat(llm)`: the provider stores why a request returned None (`LLMFailure`:
  exception type, HTTP status, message). The translator logs it, and a
  placeholder-free reply is logged as an extraction failure, not an API failure.
- `feat(epub)`: each chunk that leaves the normal path records its reason
  (`placeholder`, `raw`, `api`), its attempt count and the per-call causes. The
  record is kept in the per-file partial state and, after the file completes, in
  the job progress (`epub_fallback_units`). It is cleared when the chunk is
  translated again.
- `feat(literary)`: `queue retranslate-fallbacks --book-id N` lists the flagged
  chunks (dry run). With `--apply` it resumes the checkpoint with
  `--retry-token-aligned`, which re-translates the flagged chunks and any
  unfinished chunk through the normal EPUB path.
- `feat(epub)`: the body reconstruction reports the text coverage of each
  reconstruction and warns below 99%. A dropped passage now shows up in the log.
- `feat(epub)`: the high-rate warning waits for 20 processed chunks per file
  (was 5). Logging only.

Commits (branch `claude/friendly-elion-fdd7f5`, not pushed):

- `2b820d2` feat(llm): record why a provider request returned no response
- `723fefe` feat(epub): record reason and attempts of each chunk fallback
- `35dc830` feat(epub): report the text coverage of each body reconstruction
- `405f3dd` feat(literary): add queue retranslate-fallbacks repair command
- this note: docs(review) (see `git log`)

## Using the repair

Dry run (changes nothing):

```bash
venv\Scripts\python.exe -m src.literary.cli queue retranslate-fallbacks --book-id 11
```

Apply (re-translates the flagged chunks and rebuilds the EPUB; the queue state is
not changed, so review, refine and approve again afterwards):

```bash
venv\Scripts\python.exe -m src.literary.cli queue retranslate-fallbacks --book-id 11 --apply --parallel 1
```

## Limits

- Job 24 started on the old code, so it has no `epub_fallback_units` index. The
  repair still finds its flagged chunks through `epub_degraded_units` and reports
  them as `unrecorded`.
- Only the Ollama provider records the failure cause. Other providers still
  return None without one, and their log line says that no cause was recorded.
- Not run against the live book: the job is still running, and the app
  container must not be restarted.
- The coverage check measures characters, not meaning. It catches dropped text,
  not a wrong translation.

## Verification

- `venv\Scripts\python.exe -m pytest -q tests/unit tests/literary`: 2454 passed, 6 skipped, 0 failed (exit 0) on the four commits.
- New tests: `tests/unit/test_llm_failure_cause.py`,
  `tests/unit/epub/test_chunk_fallback_records.py`,
  `tests/unit/epub/test_body_reconstruction_coverage.py`,
  `tests/literary/test_fallback_repair.py`. Mocks and a MockTransport only; no network.
- The `/verify` (running app) check was not run: the change is not UI-facing and
  the app container must not be restarted.
