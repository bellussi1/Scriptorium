# Active context

Handoff between sessions. Read this first; update it before you stop. It must
describe the real repository, not a plan. Status as of 2026-11-19 (18:00 local):
revalidate with `git status` and `git log` before acting. Older handoffs, the
resolved decisions and the long tooling notes are in
[`archive/ACTIVE_CONTEXT-2026-11-19.md`](archive/ACTIVE_CONTEXT-2026-11-19.md)
(verbatim, compacted on 2026-11-19; earlier compaction: 2026-11-12).

## Now

- **Calibre and Kindle (2026-11-19, owner request):** the nine Robin Hobb pt-BR EPUBs from `translated_files/kindle/Robin Hobb` were added to the Calibre library with `calibredb add` (book ids `452` to `460`; backup of `metadata.db`: `data/tmp/calibre-metadata-before-hobb-pt-2026-11-19.db`; one harmless page-count traceback on a temp file) and copied over MTP to `documents/Biblioteca` on the Kindle (all nine confirmed). The Kindle's `metadata.calibre` was not updated; Calibre registers them on its next connection. Not in Calibre or on the Kindle: The Rain Wild Chronicles (still partly English). KOReader log read from `koreader/crash.log` (copy in the session scratchpad): last close on 2026-11-19 18:22 exited with code `0`; exit code `85` is a normal restart. Suspected slowness causes, not yet changed: a flat `documents/Biblioteca` with `656` entries, Cover Browser subprocess errors (`bookinfomanager.lua:492`, twice), plugins that fail to load every start (`bookshelf.koplugin` has no `main.lua`, `hardcoverstatebatch` has no `_meta.lua`) and a `crash.log` of `513` KB that is never rotated.

**Book 4 of `#33 The Rain Wild Chronicles` is still partly in English (`403` chunks, `20` files). The abort-on-billing code and a `US$ 0.50` cost guard are done (uncommitted). A local Index-Translate-9B resume was started and stopped by the owner; the real retranslation waits for Gemini credit next month.**

- **Local resume, stopped on request (2026-11-19, 18:04-18:25 local, no API spend):** `translate.py --provider ollama -m hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M --translation-id cli_7193a4e9` (log `data/queue-runs/rain-wild-book4-rescue.log`) retranslated `24` chunks and was stopped with SIGTERM (`kill_translation`, exit `143`, last counter `2115/2492`, checkpoint chunk `35/41` of Book 4 chapter 8). Result vs the backup: Book 3 chapters 7 and 11 and Book 4 chapter 7 are complete (1 chunk each); Book 4 chapter 8 went from `27` to `6` untranslated chunks; the other `19` files are untouched. State is valid and resumable. The main output EPUB was not rewritten (same hash as the backup, mtime `15:45`); the new text lives only in `xhtml_states` and in the three completed `data/uploads/cli_7193a4e9/translated_files/OEBPS/text/*.xhtml`. Left in English: Book 4 chapters 8 (6 chunks) to 22, Epilogue, Copyright, Credits, About the Author, About the Publisher (`403` chunks in `20` files). The jobs mirror now shows `20` unfinished files.
- **Decision 2026-11-19: keep the 24 local chunks, no restore** (restoring needs the states and the live jobs.db row changed together, for 24 of 2492 chunks; review them for pt-PT when the book is finalized: Book 3 chapter 7 chunk 12, Book 3 chapter 11 one chunk, Book 4 chapter 7 one chunk, Book 4 chapter 8 `21` chunks). How a restore would work, if wanted: the backup below is that state (taken 17:56, before the local run; Gemini last wrote at 15:42, nothing wrote in between). Restoring means copying `uploads-cli_7193a4e9/` back over `data/uploads/cli_7193a4e9/` and writing the `cli_7193a4e9` row of `jobs.live.db` back into `/app/state/jobs.db` while no translation runs; it discards only the `24` local-model chunks, goes back to `427` untranslated chunks in `23` files, and leaves the EPUB, queue DB and Gemini text untouched. Keeping the local chunks instead is also safe: a Gemini resume would only redo the remaining `403`.
- **Finalization script (not in the repo):** `finalize_rain_wild.py` (in the side-session notes folder) fixes `Also_By.xhtml` (rebuilds the stray `A Herança` entry and the small-caps headings; dry-run verified on a copy) and then runs the runner's local repair chain, fills `refined_output` in the run report and leaves the queue DB alone. Run it after the retranslation finishes.
- **Blocker for Haiku (2026-11-19 17:55 local):** a one-call smoke test of `anthropic/claude-haiku-5-5` through `LiteLLMProvider` in the container got `Your credit balance is too low to access the Anthropic API` (HTTP 400). No spend, no ledger row; the new abort classified it correctly (`BillingExhaustedError`). The `US$ 1.54` Anthropic balance in `data/budgets.json` is stale. OpenRouter also failed (`Missing Authentication header`, `/credits` returned 401), so its key in `.env` is not usable. The Haiku route needs an Anthropic top-up; the plan now is Gemini next month. Resume command for the Haiku route, if it is ever funded:
- Backup taken before anything else (`data/backups/rain-wild-book4-2026-11-19/`, gitignored): `uploads-cli_7193a4e9/` (`xhtml_states`), `jobs.live.db` (online backup of `/app/state/jobs.db`), `jobs.mirror.db`, `literary_queue.db`, the three `The Rain Wild Chronicles (pt-BR)*.epub`, queue run log and report. Nothing else was changed: queue DB, checkpoint and EPUBs are as the Gemini run left them.
- **Cost guard (`src/core/llm/cost_guard.py`, uncommitted, `tests/unit/test_cost_guard.py` + 2 LiteLLM tests):** `LiteLLMProvider` enforces `LLM_MAX_COST_USD` per `LLM_COST_BOOK` / `LLM_COST_STAGE` label, checks before every request, appends one row per paid call to `data/cost_ledger.jsonl` (with `cap_usd`), counts the label's earlier ledger rows on a resume, and raises `BillingExhaustedError` (exit `3`, checkpoint kept) at the cap. Fails closed on a bad cap or a model with no price in `src/literary/cost.py`. Off when the variable is unset.
- Resume command (container mounts `src` and `translate.py`, so no restart; do not restart it; from Git Bash prefix `MSYS_NO_PATHCONV=1` or the `/app/...` paths get mangled; for Gemini swap `--provider gemini -m gemini-3.8-flash` and drop the `LLM_*` variables):
  `docker compose -f docker-compose.dev.yml exec -T -e PYTHONUNBUFFERED=1 -e LLM_MAX_COST_USD=0.50 -e "LLM_COST_BOOK=The Rain Wild Chronicles" -e LLM_COST_STAGE=translate-rescue app python translate.py -i /app/data/calibre/prepared/the-rain-wild-chronicles.epub -o "/app/translated_files/The Rain Wild Chronicles (pt-BR).epub" -sl English -tl "Portuguese (Brazil)" --provider litellm -m anthropic/claude-haiku-5-5 --glossary /app/data/compiled/the-rain-wild-chronicles-glossary.json --custom-instruction queue-the-rain-wild-chronicles.yaml --no-color --parallel 3 --translation-id cli_7193a4e9`

- State of `#33` (`needs_review`, `translation_id cli_7193a4e9`, live checkpoint in the `jobs_state` volume, mirror `data/jobs.mirror.db`): Gemini prepayment credits ran out (`HTTP 402`) at Book 4 chapter 8 and the translator saved the source text as a fallback. Verified from `data/uploads/cli_7193a4e9/xhtml_states/`: `427` chunks are `untranslated` in `23` files (Book 4 chapters 8-22, Epilogue, Copyright, Credits, About the Author, About the Publisher, plus one chunk each in Book 3 chapters 7 and 11 and Book 4 chapter 7); `319` are `translated` and `11` `token_aligned`. The job progress already lists them (`epub_unfinished_units`: `23` files, `427` chunks), so a plain resume re-enters exactly those chunks (retry tickets in `src/core/epub/translator.py`).
- **Do not clear `xhtml_states` before the resume.** While the job still lists a file as unfinished, a file with no partial state is skipped (`epub_retry_state_missing`), so clearing the states would translate nothing, and it would also throw away the `319` good chunks. If a clean redo of the 16 leaking files is wanted, clear their states and their `epub_unfinished_units` entries together, after a backup.
- Also open on `#33`: `Also_By.xhtml` has the `A Herança` entry outside its `<p>` (the one `EPUBCheck` error), and `refined_output` is empty, so there is nothing to split yet.
- **Billing abort (code, uncommitted, tests pass):** a depleted wallet now stops the run instead of saving English. `BillingExhaustedError` (`src/core/llm/exceptions.py`) is raised by `GeminiProvider` (HTTP `402`, `prepayment`, `billing`) and `LiteLLMProvider` (`BudgetExceededError`, status `402`, `credit balance is too low`, `insufficient balance`, `insufficient_quota`, ...). It is re-raised through `translate_chunk_with_fallback`, the correction and refinement loops, `plain_text_pipeline` and `translate_epub_file`; the chunk loop persists the finished prefix and leaves the failed chunk pending. `translate.py` exits with code `3` (`BILLING_EXHAUSTED_EXIT_CODE`) and sends the failure notification; `src/literary/queue_runner.py` then pauses the job and the book (state `paused`, checkpoint kept), honors a pause-now so `scripts/auto_queue.py` stops the queue, and skips repair and finalization. Before this, `translate.py` logged the error and exited `0`, so the runner went on to repair a half-translated output.
  - Tests: `tests/unit/test_billing_exhausted.py` (7 tests) plus the updated `tests/unit/test_gemini_response_parts.py` and `tests/unit/test_litellm_provider.py`. `pytest -q tests/unit tests/literary tests/test_xhtml_chunk_interruption.py tests/test_common tests/test_frontend_i18n.py` gave `2729 passed` (with the cost guard). `ruff` is clean on the touched files except one more `E402` in `translate.py` (the import-after-`ensure_utf8_stdio()` pattern already there).
- Where the earlier tools stopped: Antigravity/Gemini session `1476aaa3` ("Project Context Analysis", last activity 12:25) and the Claude Code session behind the `2026-11-19 15:55` entry (in the archive) left `#33` at `needs_review` with the plan above. OpenCode left no state for this repo: `.opencode/` holds only the `literary-context` plugin and its `memoria.md` has no Rain Wild entry. The project has no `.antigravity` or `.gemini` folder; those live under `C:\Users\Bellussi\`.
- Next, in order (the owner approved "resume without clearing" on 2026-11-19; waiting on funds): resume `cli_7193a4e9` with the command above (Haiku 5.5 is `US$ 0.10 / 0.50` per 1M tokens in `src/literary/cost.py`, about `US$ 0.15` for the `427` missing chunks); fix `Also_By.xhtml`; run the local repair and finalization (the sequence in `run_queue_book` after the translation step: dropcaps, DPUB roles, ids, hygiene, progressive, reader repair, metadata, `EPUBCheck`, `validate_epub_pair`; it must also fill `refined_output` in `data/queue-runs/the-rain-wild-chronicles.report.json` so `audit_book.py` finds the file); `scripts/audit_book.py --no-cloud`; check residual English. Then split into the four volumes (exact `split_omnibus.py` command in the `14:15` entry of the archive). No Gemini or DeepSeek for this rescue.

**Queue at a glance (`data/literary_queue.db`, 2026-11-19):** `9` books `completed` and exported (`#4`, `#2`, `#3`, `#1`, `#6`, `#5`, `#16`, `#17`, `#18`; `$26.20` of the `$40.00` monthly Gemini cap spent before `#33`), `#33` `needs_review`, `19` `pending` on `gemini` / `gemini-3.8-flash`. On 2026-11-19 the audit and queue UI metrics were fixed (glossary snapshot from `report.assets.glossary_host`, `validation` derived when missing, `Termos` / `Ocorr.` pills). Remaining audit flags: `#4` 2 forbidden renderings, `#2` occurrence `89.64%`, `#1` flags `SHE`, `#16` and `#18` per-file coverage below `0.8` in 2 files.

## Books

| Group | Queue ids | State |
| --- | --- | --- |
| Tawny Man (`Fool's Errand`, `The Golden Fool`, `Fool's Fate`) | 4, 6, 5 | completed, exported to `translated_files/kindle/` |
| Liveship Traders (`Ship of Magic`, `The Mad Ship`, `Ship of Destiny`) | 2, 3, 1 | completed, exported |
| Fitz and the Fool (`Fool's Assassin`, `Fool's Quest`, `Assassin's Fate`) | 16, 17, 18 | completed, exported |
| The Rain Wild Chronicles (omnibus of 4) | 33 | `needs_review`: Book 4 partly English, see Now; split tooling ready (`scripts/split_omnibus.py`, `scripts/register_split_volumes.py`) |
| Sun Eater 2-7 (`Howling Dark` .. `Shadows Upon Time`) | 10, 8, 11, 7, 9, 13 | pending (old Index-9B outputs archived, Kindle exports kept) |
| Lonesome Dove | 32 | pending (same) |
| Malice, A Time of Dread, A Little Hatred | 29, 30, 31 | pending |
| Malazan 1-10 | 19..28 | pending, last in queue, no glossary terms |
| Farseer trilogy | not queued | official PT-BR exists; reference pairs in `data/editorial_samples/` |

## Procedures

**Re-queue a completed book.** `completed` has no outgoing transitions. Set
`books.status = 'pending'` (after a backup of `data/literary_queue.db`), set the
model with `queue set-model`, then check `queue plan --book-id N` (no issues).
Move the old EPUBs out of `translated_files/` first: a fresh run refuses to
overwrite an existing output. A resume only happens from `paused`/`interrupted`
with a resumable checkpoint.

**pt-BR revision of a finished Sun Eater EPUB** (`src/literary/ptbr_revise.py`).
1. Count: `python -m src.literary.ptbr_revise --dry-run --epub <refined> --out <tmp>`.
2. Run: same command without `--dry-run`, with `--report <json>` and
   `--model hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M`. Word swaps are
   applied directly; verbs and "tu" go to the model (about 20 s per call).
3. Gates on the output: `validate_epub_pair` against the English source,
   EPUBCheck 0 errors, and `audit_book.py --report <queue run report>` (the
   report points the audit at the refined file).
4. Read ten changed paragraphs against the English source. Only then replace
   the refined file; keep a `.pre-ptbr` backup.
Known limits: the model converts about half of the verb and "tu" cases; the
guard refuses unrequested changes; refused paragraphs stay European and are
listed in the report.

**Refine pass.** `refine-epub` pairs the source and the draft paragraph by
paragraph. Final reader-repaired files no longer pair (Howling: 0 of 94
documents). Do not re-run it on finals; see
`docs/project/reviews/local-model-ceiling-2026-11-12.md`.

## Gates and tooling

- Deterministic audit (`scripts/audit_book.py`): glossary coverage ≥ 0.90 by unique
  term against the run snapshot (`report.assets.glossary_host`, or the compiled
  `data/compiled/<slug>-glossary.json` when the report has no assets) and ≥ 0.80
  per file by occurrence, forbidden renderings 0, pt-PT ≤ 50/100k, English leakage
  ≤ 0.01, repetition ≤ 0.05, length ratio 0.80–1.20. Glossary matching ignores
  case (2026-11-12). Drift between the snapshot and the current glossary is a
  warning, not a failure.
- Cloud audit needs an approved cap (`--max-cloud-usd`). No cloud spend now.
- pt-BR checker (`src/literary/ptbr.py`) flags European Portuguese: `tu` with its
  verbs, `estar a` + infinitive, de facto, contacto, demónio, prémio, -ámos,
  convosco, teu/tua. Refine and the revision both use it.
- Reader repair terms and headings per book: `literary-resources/christopher-ruocchio/sun-eater/reader-repairs.yaml`.
  The resource loader reads any top-level `terms` key as glossary; do not use it.
- Post-passes: `src/literary/chapter_titles.py` (titles from the map; `--relabel`
  with `--titles` for translated titles), `src/literary/chapter_headings.py` (Ship
  aligner; not for files that already have headings).
- Container `translatebook-literary-dev` (127.0.0.1:5000) mounts `src` read-only:
  restart it to load Python changes; no rebuild needed.
- Tests: `venv\Scripts\python.exe -m pytest -q tests/unit tests/literary tests/test_frontend_i18n.py`.
  `tests/unit/conftest.py` points `LITERARY_QUEUE_DB` at an empty file per test, so the
  translate routes no longer see the live queue: 2226 pass in `tests/unit` with a translation running.

## Queue runtime

- **Never restart the app container while a translation runs.** The runner executes
  the translation through a `docker compose exec` it owns on the host; a container
  restart closes that exec and the job dies with exit 137 (seen three times on
  2026-11-11 at 22:51, 22:59 and 23:26). Wait for the job to stop, or pause it first.

- Single writer: the app spools each change to `data/literary_queue.intents/`;
  the host agent applies them in order (every 0.5 s, also during a run). Design:
  `docs/project/reviews/single-writer-design-2026-11-11.md`.
- Live jobs DB: named volume `/app/state/jobs.db`; host mirror `data/jobs.mirror.db`.
  Journal mode DELETE (no WAL on the bind mount).
- Known defects: a job can stay `running` after a complete resume (not reproduced,
  see decision 6); the watchdog is monitor-only; UI reads still cross the bind
  mount (design §9).

## Open decisions

1. **Imperium vs Império.** The freeze is merged; Demon and Howling keep "Império" by owner decision.
2. **Owner confirmations:** the "Scriptorium" name; upstream issue #333 is open.
3. **Watchdog: keep monitor-only.** Killing a translation from the watchdog is destructive (a container restart already kills the job with exit 137).
4. **Queue UI reads across the bind mount (design §9): deferred.** No user-visible failure recorded; it is an architecture change.
5. **Malazan glossary: not queued.** Building it means deciding pt-BR policy for hundreds of invented names; it needs the owner's naming decisions first.
6. **24 h destructive test: blocked** until the queue is idle and the dedicated app is up.
7. **Not reproduced:** a job left `running` after a complete resume (`cli_7193a4e9` still reads `running` in the mirror after its process exited). It needs a live case to trace.
8. **Meaning gate (Howling).** Howling was approved by hand; option 5 of `adjudicator-calibration-2026-11-11.md` (human review on any confirmed candidate) stays the recommendation and needs a blind run first.

## Model policy and evidence

- **Gemini 3.8 Flash (`gemini` / `gemini-3.8-flash`, `thinkingBudget: 0`) for the queue:** `100%` `name_recall` and `$13.02 / 1M` words in the Hobb pilot (`docs/project/reviews/hobb-gemini-pilot-2026-11-18.md`). The Gemini wallet is empty as of 2026-11-19 (`HTTP 402`); top it up before running more Gemini books.
- **Claude Haiku 5.5 via LiteLLM** (`--provider litellm -m anthropic/claude-haiku-5-5`, `ANTHROPIC_API_KEY` in `.env`) is the route chosen for the Rain Wild Book 4 rescue only, capped at `US$ 0.50`. The Anthropic balance is empty as of 2026-11-19 (`credit balance is too low`).
- Local `Index-Translate-9B` remains only in archived prior runs (`translated_files/archive/index9b-completed-2026-11-18/`, offline fallback). Evidence: `docs/project/reviews/sun-eater-model-selection-2026-11-10.md`, `local-model-benchmark-2026-11-10.md`, `local-model-ceiling-2026-11-12.md`.
- Balances / caps (`data/budgets.json`): Gemini monthly `cap_usd: 40.0`, Anthropic `US$ 1.54` (stale, now empty), DeepSeek `US$ 1.38` (snapshots from 2026-11-10 in the file). Ledger: `data/cost_ledger.jsonl`.

## Repository

- Branch `main`. Keep untracked user files out of commits (`.taste-skill/`,
  `Custom_Instructions/sun-eater-2.yaml`).
- Product name is Scriptorium; upstream credits, `tbl-*` EPUB ids, localStorage
  keys and `TBL_*` variables stay on purpose.
- Prompt library status: `docs/prompts/README.md` (top block).
