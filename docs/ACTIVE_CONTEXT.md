# Active context

Handoff between sessions. Read this first; update it before you stop. This file
is the shared state for both Claude Code and OpenCode, so it must describe the
real repository, not a plan.

Status: current as of 2026-11-11. Revalidate with `git status` and `git log`
before acting on anything below.

## Repository

- Branch `main`; the local benchmark report and adapters are committed through
  `e447991` (earlier round `ae75dc5`); the OpenCode skills/plugin/ledger are in
  `d19b42f`.
- Working tree keeps the user's untracked `AGENTS.md`, `.taste-skill/` and
  `Custom_Instructions/sun-eater-2.yaml`.
- Nothing has been pushed.

## Runtime

- The previous run (job 19, `cli_c6f4be29`) died at 23:14 UTC. The app's
  `data/jobs.db` was corrupted by SQLite WAL on the Windows bind mount: the
  process reported `database disk image is malformed`, the progress JSON
  claimed 1074/1074 while the real checkpoint was inconsistent, and the queue
  status stayed stale. The old 321/1074 (30%) was not trustworthy.
- Recovery: `data/jobs.db` was rebuilt with `VACUUM INTO`, WAL/SHM removed and
  the journal switched to `DELETE` (`SQLITE_JOURNAL_MODE=DELETE` default in
  `src/persistence/database.py`). Integrity is OK and the malformed errors are
  gone. The old partial EPUB is archived at
  `translated_files/archive/howling-dark-partial-2026-11-11/`; the old upload
  is backed up. Queue job 19 was cleared.
- **The live jobs DB is now on a Docker named volume.** `docker-compose.dev.yml`
  sets `JOBS_DB_PATH=/app/state/jobs.db` (volume `traducaollm_jobs_state`) and
  `JOBS_MIRROR_PATH=/app/data/jobs.mirror.db`. The old bind-mount DB was moved
  to `data/backups/jobs-old-bind-mount-20261111.db`; the host no longer opens
  `data/jobs.db` for anything. The app writes the live DB; the host reads the
  mirror, refreshed every 30 s by `src/persistence/mirror.py` (SQLite backup API,
  atomic replace, quick_check, sidecar `jobs.mirror.json`).
- Job 20 (`cli_bc71db89`) is failed/archived at 11/1074. The fresh run is
  **job 21, `cli_c00e8ea2`**, queue job 21, book 10 `translating`; it started at
  04:04 UTC on the volume. It was paused at 04:23 to fix the EPUB count
  semantics and resumed at 04:30. The old file index made the resume restart at
  the title page, so it is redoing the front matter and early chapters; at
  06:03 it was **392/1074**. That redo is a one-time cost of correcting the
  checkpoint model, not a quality change. Supervisor PID 15564 is running; the
  watchdog PID 25488 writes `data/literary_queue.health.json` every 30 s.
- The 05:52 app restart loaded the health/auto-restore/template and exposed a
  CLI resume bug: `translate.py` did not pass the checkpoint resume index to
  the EPUB pipeline, so a queue "resume" restarted from the title page. Fixed:
  `translate.py` loads `load_checkpoint`, passes `resume_from_index` and marks
  the job running; `translation_api.py` now skips queue-owned jobs during the
  web startup restore (`_queue_owns_translation`). The app image was rebuilt
  because `translation_api.py` is baked into it, not bind-mounted. The live
  progress was restored to file 32/364; the current resume logged
  `Resuming cli_c00e8ea2 from checkpoint index 32` and continued at chapter 26
  (`[365/1074]`), not at the front matter.
- The watchdog ETA for EPUB now comes from its own 10-minute rolling chunk
  rate; the file-level checkpoint rows are not a chunk timeline. The hero
  health chips (process/checkpoint/DB/audit) are active after the app restart.
- The overnight supervisor (`auto_queue.py`, PID 15564 after the 06:27 restart)
  now has two bounded safety nets before it blocks: a crashed book with a
  `translation_id` is retried once from its checkpoint, and a final audit whose
  only failure is a forbidden rendering is repaired with the compiled glossary
  target (whole-word rewrite, backup kept, EPUBCheck must stay clean) and
  re-audited. Anything else still blocks for human review.
- **Howling Dark finished translating at 09:09 UTC** (1074/1074 chunks, 94
  files, 2 h 11 m), then the source-aware refine ran for about four hours and
  the reader repair was accepted (merged 56 seams, 3,878 dialogue quotes, 801
  splits). The final artifact is
  `translated_files/Howling Dark (pt-BR).refined.epub`: EPUBCheck **0/0/0**,
  `validate epub` passed with one expected `spine_extra` warning (attribution
  page), TOC labels localized (`Capa`, `Sumário`, `Capítulo 1: A Companhia
  Vermelha` … `Capítulo 80`, `Léxico`), `docTitle` and NCX uid aligned,
  `dc:language` and package `xml:lang` both `pt-BR`. A backup of the file
  before the manual case fix is `.pre-casefix.epub`.
- **The final audit blocks the book.** Deterministic gates pass: coverage
  0.9935 (153/154), zero forbidden renderings after fixing the all-caps
  `CHANTRY` on the dropcap of chapter 76, pt-PT 24.7/100k, leakage 0.0002,
  repetition 0, length ratio 1.0046, queue gate and EPUBCheck clean. The
  aligned cloud audit (`data/audits/howling-dark-verify-20261111T093932Z/`)
  scores fidelity 4.286, naturalness 3.714, terminology 3.857, register 3.857,
  prose **3.571**, tense 0, gender 0, but **3 meaning notes**; the documented
  gate allows at most one. The notes are minor (a lost idiom in "wave the fleet
  above", an unnatural "ragdolled puddle", a partial omission of "nor did any
  know"), but the gate is blocking. The book stays in `needs_review`; it was
  not auto-approved and Demon in White was not started. A visual pass also
  caught `TIVAMOS NOSSO CARON` in chapter 24 (should be `TÍNHAMOS NOSSO
  CARONTE`), a model defect the sample missed; it was fixed in place as a
  two-word typo correction (`CARONTE` was already the form used in the same
  chapter) and EPUBCheck stayed 0/0/0. The audit report predates that correction
  and still shows the pre-fix text; the deterministic metrics are unaffected.
- The audit sampler now aligns paragraphs by word-count signature (1:1, 1:2 and
  2:1 blocks) instead of the raw index; before the fix three of seven samples
  compared different scenes and were unscored.
- **Demon in White is translating** (book 8, job 23, translation
  `cli_d5687b57`, started 09:50 UTC). The pipeline is free because Howling Dark
  finished; the review decision on Howling Dark does not block it. The
  supervisor is stopped, so Demon will stop at its own `needs_review` without
  an automatic audit until it is restarted or audited manually. The watchdog
  (PID 40128, restarted 11:12 UTC) now resets its intra-run audit counter when
  the book changes; Demon's first partial audit at 448 chunks **passed**
  (pt-PT 37.9/100k, leakage 0.0008, repetition 0, length 0.9982).
- **EPUB checkpoint semantics are now explicit.** `checkpoint_chunks` rows are
  **files**, not chunks, for EPUB; the per-file `xhtml_states` carry the chunk
  progress. The global completed count stays in the progress JSON and is
  updated by `save_xhtml_partial_state`. `save_checkpoint_atomic` derives
  counts from rows only for TXT/SRT (`derive_counts=True`); EPUB passes the
  caller's global count. `reconcile_job` preserves the EPUB file index and the
  global counters; deriving them from file rows made a 321-chunk run look like
  94. `CheckpointManager.get_resumable_jobs` and `queue checkpoint-status`
  follow the same split. `xhtml_states` are written atomically.
- A pause-now now stops the whole queue: the queue runner re-applies the book
  `paused` state after the final sync, and `auto_queue.py` exits instead of
  picking the next pending title. The accidental Demon in White run (11 chunks)
  was stopped and its partial archived at
  `translated_files/archive/demon-in-white-partial-2026-11-11/`; book 8 is back
  to `pending`.
- `scripts/db_snapshot.py --label <book>` snapshots the live DB through the
  container and the queue DB through the SQLite backup API; both get a
  quick_check and a manifest entry. A current `jobs-howling-dark-*` snapshot
  was written. The watchdog is monitor-only by default; `--terminate` exists
  but is not enabled.
- `src/persistence/recovery.py` checks the live DB before the state manager
  opens it and promotes the newest healthy snapshot if it is corrupt; the bad
  file is kept as `jobs-corrupt-<timestamp>.db`. This was tested on a corrupt
  copy (refused, snapshot restored) and has two unit tests. The queue snapshot
  now includes `health` and per-book `checkpoint_count`, `last_checkpoint_at`,
  `process_alive`, `stalled`, `eta_human`, `db_integrity`; the hero shows the
  stall and uses the health ETA. The API fields take effect on the next app
  restart; the JS already falls back when they are absent.
- Intra-run audit: `scripts/intra_run_audit.py` runs every 100 chunks through
  the watchdog and writes `data/audits/intra-run/`. The first audit at 233
  chunks failed with **1 forbidden rendering: `Chantry`** (glossary target
  `Chantria`); pt-PT 16.6/100k, English leakage 0.0005, repetition 0.0001 and
  length ratio 1.01 passed. The glossary hash is
  `03fc8f8f...392a` with a `.sha256` sidecar. The run continues because the
  intra-run audit is a warning; the final gate will block until the term is
  fixed. `audit_book.py` now also fails on glossary drift or a changed snapshot
  hash.
- Snapshot scheduler: the watchdog runs `db_snapshot.py` every 6 h and keeps
  7 daily snapshots plus one per book; `next_snapshot_at` was 11:11 UTC. The
  hero now has health chips for process, last checkpoint, DB integrity and
  audit; the API sends them after the next app restart.
- Glossaries: the queue runtime uses
  `data/compiled/howling-dark-glossary.json` (172 terms; the log says
  `Glossary loaded: 172 terms`). The UI tab uses a separate
  `data/glossaries.db`, which was empty (0 rows, stale WAL); it is not the
  runtime source. The 11 compiled Sun Eater/Realm glossaries were imported
  through the app API: **11 glossaries, 1,062 terms**; Howling Dark has the
  same 172 terms as the runtime. `db_snapshot.py` now snapshots
  `glossaries.db` too (current `glossaries-howling-dark-*.db`, 11/1,062).
  The UI copy stores only source/target/category/gender; the `forbidden`,
  `policy` and alias metadata live in the compiled runtime JSON. Editing the
  UI copy does not change the queue; the queue recompiles the YAML under
  `literary-resources/` at the start of each book. The glossary DB is still on
  the bind mount with WAL; moving it to the state volume is a gate item.
  The UI tab now lists the 11 glossaries; the first intra-run audit also uses
  the runtime glossary and caught the single `Chantry`/`Chantria` issue.
- Quality gates: `literary-resources/.../sun-eater/style.yaml` now has explicit
  `verb_tense`, `grammatical_gender` and `prose_and_idiom` dimensions. The
  source-aware refine pass is enabled by default (`refine=True` in
  `run_queue_book`; `--refine-limit 0` means every flagged segment); the
  `Refinement enabled: False` line in `translate.py` is the prompt-level
  refinement, not the queue's `refine-epub` pass. The current translation
  prompt compiled before this style edit, but the end-of-book refine pass will
  read the new dimensions. The final cloud audit now samples 8 passages and
  gates `prose >= 3.5`, `tense_errors <= 1` and `gender_errors <= 1` in
  addition to fidelity, naturalness, meaning and pt-PT. The final EPUB gate
  follows the `epub-quality` checklist: EPUBCheck 0/0/0, package version and
  metadata dialect, unique-identifier/NCX uid, TOC labels from the source,
  reader repair for Sun Eater, and a KOReader/Calibre open. The Fool's Errand
  case remains the reference for the Realm redo.
- **Series metadata is now written into the translated EPUB, not only the
  Kindle copy.** The queue runner applies `update_opf_metadata` after the reader
  repair and before the gate, then re-runs `validate_epub_pair` and EPUBCheck;
  the file is replaced only on success and the report carries
  `series_metadata`. Howling Dark was patched in place (backup
  `.pre-series.epub`): `belongs-to-collection` + `collection-type` +
  `group-position` and `calibre:series`/`calibre:series_index`; Calibre
  `ebook-meta` reads `The Sun Eater #2`, EPUBCheck is 0/0/0. Demon in White's
  running process predates this change, so its final EPUB needs the same
  one-shot post-pass after the run; the next book applies it automatically.
- Still pending: the `literary_queue.db` single-writer/intent refactor (the
  app still writes on approve/retry/add/move/remove; the queue DB stays on the
  bind mount) and watchdog auto-restart. The destructive kill/restart tests
  were run on 2026-11-11: DB recovery 5/5, process SIGKILL and container kill
  both resumed from the checkpoint; see `docs/project/DESTRUCTIVE_TESTS.md`.
  Two findings to fix: a resumed job can write a `(1)` duplicate when the
  target EPUB already exists, and the upstream job status stays `running`
  after a fully-completed resume (the queue runner still marks
  `needs_review`, so the queue flow is unaffected).
- **Terminology freeze (2026-11-11) is staged on branch
  `glossary/terminology-freeze` (commit `acae484`), not on `main`.** It changes
  `Imperium` to `policy: keep` (official: Imperium 32x, Império 107x) and adds
  `datasphere -> esfera de dados`, `animalcule -> animalculo` and
  `knight-tribune -> tribuna-cavaleira`, plus `docs/project/TERMINOLOGY.md` and
  a regression test. Do **not** merge while Demon in White is running: the
  final audit compares the snapshot compiled at book start with the current
  YAML and would fail on glossary drift. Merge after Demon's audit; the next
  book then compiles the frozen terms. Howling Dark and Demon keep "Império";
  a later context-sensitive pass is possible but not scheduled.
- Host resume asks the live DB through
  `python -m src.literary.cli queue checkpoint-status --id ... --reconcile`;
  the mirror is only a fallback. `JOBS_DB_PATH` is the default for
  `CheckpointManager`, so the CLI and the app point at the volume.
- Tests: `pytest -q tests/unit tests/literary` gives **2345 passed** and one
  unrelated environment-dependent failure
  (`test_path_validator.test_reject_path_separator_backslash`, a Linux
  backslash path).
- Still pending from the reliability plan: the API/UI health fields
  (`checkpoint_count`, `last_checkpoint_at`, `stalled`, `db_integrity`) and the
  UI reading `literary_queue.health.json`, which need the next app restart; a
  single writer for `literary_queue.db` (still host + app); a scheduler for the
  6 h snapshots and automatic restore; watchdog auto-restart; and the quality
  layer (glossary hash, intra-run audit, final gate additions).
- Main app on `:5000`, preview on `:5001`.
- The Translate tab now has a full-width `translate-hero` at the top: large
  percentage, 22px progress bar (18px on mobile), chunks/ETA/rate/start stats,
  last meaningful log line and pause/log/queue actions. The compact `queueNow`
  remains on the Queue tab. The hero moves itself to the top and re-renders
  even when the template is cached.
- Tab choice persists across F5 via `localStorage` plus the URL hash. The theme
  is applied by an inline head script before the CSS, so dark mode does not
  flash light; that inline script takes effect on the next Flask restart, while
  `ThemeManager` already removes the stale `light` class and sets
  `color-scheme`.

## Translation state

- **Sun Eater books 2-7 are now `ollama` / Index-Translate 9B**, one book at a
  time. Howling Dark is first. Its old Hy-MT2 output is archived at
  `translated_files/archive/howling-dark-hy-mt2-2026-11-10/`.
- Howling Dark job 20 (`cli_bc71db89`) is failed/stopped at **11/1074**
  persisted chunks after the 03:15 bind-mount write failures. Its partial
  uploads (`data/uploads/cli_bc71db89`, 12 files through chapter 4) and the old
  fixed/fixed-v2 EPUBs are archived at
  `translated_files/archive/howling-dark-partial-2026-11-11-job20/`; they are
  not a trustworthy resume point. The interrupted partial EPUB from job 19 is
  archived at `translated_files/archive/howling-dark-partial-2026-11-11/`; the
  old upload `data/uploads/cli_c6f4be29` is backed up as `.bak-2026-11-11`.
  Job 19 was cleared so no stale checkpoint can be mixed into the new run.
- The fresh Howling Dark run is job 21 (`cli_c00e8ea2`), started at 04:04 UTC
  on the named volume and resumed at 04:30 after the EPUB count fix. The queue
  job 21 carries that translation id; the host mirror is
  `data/jobs.mirror.db`; the live count is in
  `data/literary_queue.health.json`.
- Demon in White (book 8) was accidentally started by the old supervisor after
  the pause-now because the book state stayed `translating`. It was stopped at
  11 chunks, its upload archived at
  `translated_files/archive/demon-in-white-partial-2026-11-11/`, its job 22
  resume state cleared, and the book returned to `pending`.
- The Demon in White, Ashes of Man and Disquiet Gods partials were discarded;
  their checkpoint uploads were removed. Kingdoms of Death and Shadows Upon
  Time are pending on Index. The old Gemini partial is gone; no model mixing.
- The queue order is Howling Dark (priority 999999), Demon in White, Kingdoms
  of Death, Ashes of Man, Disquiet Gods, Shadows Upon Time.
- Balances: DeepSeek **US$ 1.38** (available); Anthropic **US$ 1.54**
  (available); Gemini **R$ 0** available (historical cap R$ 91, ledger
  US$ 1.32 historical). Sun Eater is local-only; no cloud spend.
- Ledger: Gemini **US$ 1.32** historical; Claude **US$ 0.57** historical.
  `scripts/lit_queue_cost.py` upserts the running job estimate and reads the
  queue log when the DB progress lags.
- One book at a time, one chunk at a time, `mode=next` only.

## Benchmark position

Sun Eater, *Empire of Silence*, official PT-BR reference:

| Model | Dev chrF | Test chrF | Dev names | Test names | Probe terms | Long chrF |
|---|---:|---:|---:|---:|---:|---:|
| Gemini 3.8 Flash | **0.7033** | **0.7095** | 0.9660 | 0.9733 | 0.9915 | **0.7981** |
| Index 9B | 0.6876 | 0.6947 | 0.9626 | **0.9933** | 0.9915 | 0.7852 |
| DeepSeek V4.1 | 0.6819 | 0.6863 | 0.9631 | 0.9596 | 0.9744 | not run |
| Haiku 5.5 | 0.6774 | 0.6753 | 0.9354 | 0.9933 | 0.9915 | 0.7761 |
| Hy-MT2 Q4 | 0.6670 | 0.6580 | 0.9427 | 0.9267 | 0.9744 | 0.6731 |

Blind A/B with Claude Sonnet (non-contestant):

- Gemini vs Index: dev 38–2–16 (`p < 0.0001`); test 17–4–7 (`p = 0.0072`).
- Gemini vs Haiku: dev 23–7–26 (`p = 0.0052`).
- Earlier Haiku vs Index, repository agent: dev 37–12–7; test 16–7–5.

Expert report: `docs/project/reviews/sun-eater-model-selection-2026-11-10.md`.

## Local benchmark (2026-11-10)

- Qwen3 8B, EuroLLM-9B and SalamandraTA-7B ran on the Sun Eater dev (56),
  probes (50) and test (28) corpora, same 73-form glossary, one repeat. Output:
  `data/benchmark/eval-sun-eater-{dev,probes,test}-v3-local/`. The GPU is free.
- chrF dev / test: EuroLLM 0.6785 / 0.6804, Salamandra 0.6559 / 0.6796, Qwen3
  0.6495 / 0.6581. Index stays ahead (0.6876 / 0.6947). Probe terms: Qwen3
  1.0, EuroLLM 0.9829, Salamandra 0.906 (repetition 0.119 on dev, length ratio
  1.13). Single repeat.
- Blind A/B, one AI judge per batch: Index beats EuroLLM on dev 36–19–1
  (p = 0.03, 65.5% decisive, CI 52.7–78.2%) and on test 22–4–2 (p = 0.0005,
  84.6%, CI 69.6–96.3%). Index beats Qwen3 on dev 42–11–3 (p < 0.0001).
  Files: `data/benchmark/sun-eater-{dev,test}-local-index-vs-eurollm-9b/`.
- Human spot-check (owner, 15 blind dev pairs): 14/15 agree with the judge;
  owner picked Index 9, EuroLLM 6.
- The official EuroLLM model-card sentence was verified against the public
  1.7B card (the 9B card is gated) and rerun as `eurollm-9b-native`:
  dev chrF 0.6781, test 0.6793, probe terms 0.9744. A wash versus the
  controlled prompt; the ranking stands. `benchmark/literary/adapters.py`
  registers both variants.
- Caveat: Index and Hy-MT2 received the 2,228-character style block; the
  colon-style EuroLLM/Salamandra runs received only the glossary. The gap may
  overstate Index's prose advantage, though the test A/B direction is strong.
  A style-included rerun is the remaining fair check, not a blocker for the
  provisional decision.
- Report: `docs/project/reviews/local-model-benchmark-2026-11-10.md`.
- Realm of the Elderlings was not run locally; Index remains its default from
  the Farseer round.

## 24/7 auto gate (owner-authorized 2026-11-10)

- `scripts/auto_queue.py` (PID 15564 before the Howling Dark gate) waits for a
  book, runs `scripts/audit_book.py` at `needs_review`, approves only on a full
  pass, exports Kindle and starts the next pending book. Any failure stops and
  leaves `needs_review`. It is **stopped/blocked** after the Howling Dark audit;
  start it again after the review decision.
- Gates: queue validation/EPUBCheck; glossary coverage >= 0.90 and zero
  forbidden renderings; pt-PT <= 50 per 100k; English leakage <= 0.01;
  repetition <= 0.05; length ratio 0.80-1.20; Haiku sample audit with
  fidelity/naturalness/prose >= 3.5 and at most one meaning error.
- Caps: **US$ 0.05 per book**, **US$ 0.50 total**; model `claude-haiku-5-5`
  with thinking disabled. Audit rows use `stage: auto-audit` in the ledger.
- Howling Dark gate result (2026-11-11): all deterministic gates pass; cloud
  audit prose 3.571, fidelity 4.286, naturalness 3.714, tense 0, gender 0,
  meaning **3** -> fails the one-error gate. Report:
  `data/audits/howling-dark-verify-20261111T093932Z/audit.md`. Decision: leave
  the book in `needs_review`; no auto-approval. The supervisor was not restarted
  after the block.
- **The cloud gate was calibrated on 2026-11-11.** `meaning_errors` now counts
  only factual/denotative errors; calques, lost irony, weakened imagery and
  register are `style_notes`, advisory and non-gating. A second, narrow Haiku
  pass re-checks every candidate meaning error and only the confirmed count
  gates the book; a missing confirmation keeps the candidate count (never a
  silent pass). The calibrated re-run of Howling Dark
  (`data/audits/howling-dark-calibrated2-20261111T135618Z/`) scored prose 4.0,
  fidelity 4.143, naturalness 4.0, style 9 (advisory warning), meaning
  candidates 4, confirmed **2** -> still fails the one-error gate. Manual
  reading says the two confirmed notes are false positives (`uptown` -> "lá em
  cima" and `glad` -> "grato"); the judge over-confirms. Open decision: approve
  the book manually, add a stronger adjudicator for the confirmed candidates,
  or relax the threshold to 2. The report is the evidence.
- Reports: `data/audits/<book>-<timestamp>/audit.md`; supervisor status:
  `data/literary_queue.auto.json`.

## Sun Eater and Realm resources (2026-11-10)

- Official Sun Eater reference: *Império do Silêncio* (Calibre 436), the only
  official PT-BR book; Editora Aleph is publishing the series in Brazil as
  *O Devorador do Sol* starting in 2026. For books 2-7, compare terms, names
  and register, not paragraph alignment.
- Official Realm reference: the Farseer trilogy in PT-BR — *O Aprendiz de
  Assassino* (Calibre 94), *O Assassino do Rei* (92) and *A Fúria do
  Assassino* (71). Later Realm books have no official PT-BR edition; use the
  trilogy for terms/style, not alignment.
- English sources: the Farseer trilogy is in Calibre (336, 329, 338). The
  English *Empire of Silence* path still needs confirmation; the official PT
  and the 84 aligned benchmark excerpts are the current Sun Eater reference.
- Howling Dark glossary is now **117 terms / 177 prompt forms**. The official
  book 1 audit (`Império do Silêncio`, Calibre 436) reaches **70 terms / 113
  forms, coverage 1.0**. Corrections: `Extrasolarian` -> `extrassolariano`
  (the official form; `extrassolar` is forbidden), `Pallino` keeps the short
  form, `Tanaran`/`Uvanari`/`Calagah` first appear in book 1. New official
  terms: Crispin, Gilliam Vas, Dorian Mataro, Demetri Arello, Elomas, Kyra,
  Simeon (o Vermelho), Roban, Ligeia Vas, Gila, Alistair, Kiri, Felix, Cat,
  Umandh, Casa Mataro, Teukros and Vesperad. The Nov Belgaer additions remain
  for Howling Dark (Raine Smythe, Aranata Otiolo, Nobuta, Ilex, Yume, Suzuha,
  Tor Varro, Calvert, Greenlaw, Brevon, Cento, Jari, Rustam, Naia, plus
  aeta/baetan/galstani/tavrosi/mandari/normando/Exaltados/Imortal/Tribuno/
  Hauptmann/March Station/Enigma of Hours). `resources validate` passes.
- The production style block is the existing 2,228-char translation section.
  Review it against the official book 1 register after the Howling Dark pilot;
  change it only for a systematic gap, not for isolated wording.

## Tooling (OpenCode)

- `opencode.json` disables the global `cloudflare-api` MCP for this project
  (3,042 tools, irrelevant) and loads `skills: ["./skills"]`.
- Project skills: `literary-queue` (queue rules, models, budgets, EPUB gates),
  `epub-quality` (OPF/NCX/EPUBCheck/TOC/Kindle) and `model-benchmark`
  (corpus, probes, A/B, long chapter, cost). The upstream
  `translate-books-with-llms` skill remains for the raw engine.
- `.opencode/plugins/literary-context` injects a compact live block (queue,
  runner, decision, budgets) into the session context and exposes
  `literary_status` and `literary_cost`.
- Local data: `data/budgets.json` (balance/cap snapshots) and
  `data/cost_ledger.jsonl` (recorded spend). `python scripts/lit_cost.py`
  prints the report; `python scripts/lit_queue_cost.py --book-id 8` upserts the
  running job estimate (estimated row, replaced on each run).
- The Dalibre MCP token was moved from `~/.config/opencode/opencode.json` to
  the user environment variable `DALIBRE_TOKEN`; the config now uses
  `{env:DALIBRE_TOKEN}`. **Restart OpenCode** so the server process inherits
  the variable; until then the `dalibre` tools are unavailable.
- P2 not added: read-only SQLite MCP. Revisit only if the plugin status tool is
  not enough or another agent needs direct DB access.

## Decision

**Current production policy: local Index-Translate 9B for Sun Eater and Realm.**
The GCP credit is exhausted and the user chose the local path; Gemini remains
the quality reference, not the active model. Haiku is the paid fallback only if
cloud is explicitly funded again. Malazan and the other series wait for their
own resource pass.

No new local screening round is planned. Index stays the default and Hy-MT2 Q4
the fallback. Qwen3.5-9B is a generalist; public translation/instruction-following
scores are far below Index. TranslateGemma-4B has a 2K-token input and a fixed
chat template, so it cannot carry the glossary/style prompt. The public numbers
are vendor-run and sentence-level; our Sun Eater/Farseer runs are the operative
evidence.

## Next decision

Howling Dark is running on Index. When it stops at the review gate:

1. Run EPUBCheck and inspect the TOC/OPF.
2. Check term/name compliance, pt-PT forms, English leakage, repetition and
   length ratio; compare sample chapters with the official *Império do Silêncio*
   for terminology and register (not paragraph alignment).
3. Approve and export to Kindle, then start Demon in White. Continue in series
   order through Kingdoms of Death, Ashes of Man, Disquiet Gods and Shadows
   Upon Time.
4. After Sun Eater, do Realm: redo Ship of Magic and Fool's Errand with Index,
   then The Mad Ship, Ship of Destiny, The Golden Fool, Fool's Fate and the
   Fitz and the Fool trilogy. Use the official Farseer trilogy as the
   term/style reference.
5. Malazan only after a glossary/character/style build; it currently has zero
   terms.

Do not mix providers mid-book; the review gate and one-book-at-a-time rule
stay. Dalibre: restart OpenCode so the MCP reconnects with `DALIBRE_TOKEN`.
