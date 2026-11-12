# Active context

Handoff between sessions. Read this first; update it before you stop. It must
describe the real repository, not a plan. Status as of 2026-11-12: revalidate
with `git status` and `git log` before acting. Older handoffs are in git history
(this file was compacted on 2026-11-12).

## Now

- **Queue agent** runs from the main checkout (`scripts/queue_runner_agent.py`).
  Queue changes from the UI need it; start `start-queue-agent.bat` if it is down.
- **Running:** Disquiet Gods (Sun Eater 6, book 9) re-translated from the EPUB 3.0 library
  source, started 2026-11-12 16:43 local (about 4 h on the local GPU). The old output was
  built from the superseded EPUB 2.0 source and moved to
  `data/tmp/disquiet-gods-superseded-2026-11-12/`. When it finishes: check the gate
  (job state `needs_review`), apply the progressive repair to its output, then review.
  Shadows Upon Time (book 13) is pending. Book 9 keeps the EPUB 2.0 hash in `books.source_hash`.
- **Reviewed and approved 2026-11-12:** Ashes of Man (book 7) and Kingdoms of Death
  (book 11), both `completed`. The previous refined files are `*.refined.pre-review.epub`.
- **Sun Eater terms follow the official pt-BR edition** (Império do Silêncio): peoples and
  species in lower case (cielcin, mericanii, aeta, ...), titles mid-sentence in lower case
  (lorde, sir, imperador, comandante, ...). Books 2 to 5 were rewritten; the previous files
  are `*.pre-official-case.epub`.
- **pt-PT progressive ("estar a" + infinitive → "estar" + gerund):** `src/literary/progressive_repair.py`
  rewrites only the verbs listed in `PROGRESSIVE_GERUNDS` (nouns such as "dor" and "favor" are
  left alone). Applied to the refined files of Howling Dark, Demon in White, Kingdoms and
  Ashes (EPUBCheck 0 errors; backups in `data/tmp/progressive-repair-backup-2026-11-12/`).
  Kindle folder rebuilt. Wired into the queue run after the id repair (from this change on).
  The three leftovers were fixed by hand on 2026-11-12: "despregar" (Ashes, now "lançando"),
  and the two split by markup (Demon "estava</i> brincando", Ashes "estava <a/>gritando").
- **Kingdoms chapter 40 title** ("Que Altar Verde", literal for "What Green Altar"): kept
  (decided 2026-11-12). No official pt-BR chapter list was found online; the map in
  `literary-resources/.../chapter-titles/kingdoms-of-death.yaml` still marks it as editorial.
- **Glossary:** `eali` (Jaddian ruling caste) is `policy: keep` and approved (2026-11-12). The
  compiled Disquiet Gods glossary was rebuilt once, before that flag change.
- **Sun Eater pt-BR revision, word-swap stage: done 2026-11-12** on Demon, Howling and Kingdoms
  (guard, EPUBCheck 0, `validate_epub_pair` unchanged). Backups in
  `data/tmp/progressive-repair-backup-2026-11-12/pre-ptbr-swaps/`. The model stage (`tu`,
  second-person verbs, "estar a") is still pending: it needs the GPU, so run it after
  Disquiet Gods, in the order Demon, Howling, Kingdoms, with `--num-ctx 4096`, gating each output.
- **Queued on Index:** Ship of Magic (2), Fool's Errand (4), Ship of Destiny (1),
  The Golden Fool (6), Fool's Fate (5). Their Hy-MT2 outputs are in
  `translated_files/archive-hy-mt2-2026-11-12/`.
- **Branches:** every local branch is merged or equivalent in `main`. Two
  remote copies of merged branches remain on `origin` (`fix/epub-contributor-role`,
  `fix/glossary-forbidden`); delete them on request.
- **UI pass (buttons, tabs, completed translations):** merged into `main` by fast-forward (2026-11-12, tip
  `4eae8b6`); not pushed. Verified on a test instance at 127.0.0.1:5055
  (queue DB copy in `data/ui-check/`, gitignored): tab ARIA and arrow/Home/End keys,
  light and dark, mobile wrap, history rows. Open: at 375 px the seven tabs take three
  rows; `#glossaryListTable` is about 490 px and overflows panes under ~520 px (predates
  this pass); one 400 on a model-list request at page load is not yet identified.

- **Front-end pass (2026-11-11, merged into `main`):** stylesheets are SCSS partials in `src/web/static/scss`,
  compiled with `npm run build:css` into `src/web/static/css/app.css`; spacing and radius
  tokens are in `_tokens.scss`. Mobile media queries are gone (desktop-first).
  **Deploy step pending:** the running container still serves its cached template,
  which links the five legacy stylesheets (`style.css`, `queue.css`, `ui-polish.css`,
  `literary-theme.css`, `theme-dark.css`). Those files are untracked copies of HEAD
  kept on disk; delete them after the container restarts (after Ashes finishes).
  Not done: JS comment sweep beyond narration lines; TypeScript and HTML-generation decisions.

## Books

| Book | Queue | State | Notes |
| --- | --- | --- | --- |
| Demon in White (Sun Eater 3) | 8, completed | refined, post-passed | Titles, body headings, series metadata and Lexicon done. Audit: `Imperium` drift (owner accepted "Império"). Word swaps done 2026-11-12; model stage pending. |
| Howling Dark (Sun Eater 2) | 10, completed | refined, post-passed | Approved in the Queue UI. Headings and titles consistent (80). Chapter 50 title and "“ELA" fixed 2026-11-12. Word swaps done 2026-11-12; model stage pending. |
| Kingdoms of Death (Sun Eater 4) | 11, completed | refined, post-passed | Approved in the queue 2026-11-12, before the model stage of the pt-BR revision. Reopen if the owner wants the revision first. |
| Ashes of Man (Sun Eater 5) | 7, completed | refined, post-passed | Approved 2026-11-12. OPF scheme warning fixed (EPUBCheck 0/0/0). No chapter-title map yet. |
| Disquiet Gods (Sun Eater 6) | 9, running | re-translation from EPUB 3.0 | Started 2026-11-12 16:43 local. Then: progressive repair, gate, review. |
| Shadows Upon Time | 13, pending | — | After Disquiet Gods. |
| Ship of Magic (Realm 1) | 2, pending | to be re-translated | Was Hy-MT2 + repair. Post-pass (`chapter_headings`) was aligned to Hy-MT2 residue; redo it. |
| Fool's Errand (Realm, Tawny Man 1) | 4, pending | to be re-translated | Was Hy-MT2. Post-pass (roman numerals, `fools-errand.yaml`) must be redone; body title XXI was English. |
| Ship of Destiny, The Golden Fool, Fool's Fate, The Mad Ship | 1, 6, 5, 3, pending | Index | Hy-MT2 rows were switched to Index. |
| Lonesome Dove | not queued | — | Resources exist. Decided 2026-11-12: not queued until the Sun Eater pt-BR work ends. |
| Malazan | not queued | — | Zero glossary terms; needs a glossary build first. |

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

- Deterministic audit (`scripts/audit_book.py`): glossary coverage ≥ 0.90 overall
  and ≥ 0.80 per file, forbidden renderings 0, pt-PT ≤ 50/100k, English leakage
  ≤ 0.01, repetition ≤ 0.05, length ratio 0.80–1.20. Glossary matching ignores
  case (2026-11-12).
- Cloud audit needs an approved cap (`--max-cloud-usd`). No cloud spend now.
- pt-BR checker (`src/literary/ptbr.py`) flags European Portuguese: `tu` with its
  verbs, `estar a` + infinitive, de facto, contacto, demónio, prémio, -ámos,
  convosco, teu/tua. Refine and the revision both use it.
- Reader repair terms and headings per book: `literary-resources/christopher-ruocchio/sun-eater/reader-repairs.yaml`.
  The resource loader reads any top-level `terms` key as glossary; do not use it.
- Post-passes: `src/literary/chapter_titles.py` (titles from the map; `--relabel`
  with `--titles` for translated titles), `src/literary/chapter_headings.py` (Ship
  aligner; not for files that already have headings).
- Front-end TypeScript: sources are `.ts` next to the modules they replace; `npm run build`
  emits the `.js` files the browser loads (no bundler, same ES module graph). Check with
  `npm run typecheck` (strict). Commit the generated `.js` with the `.ts`. Migrated so far:
  `translation/progress-title`. Next: `queue/queue-manager.js` (2,035 lines; strict run gives
  264 errors: ~100 untyped parameters, ~80 DOM property accesses on `HTMLElement`, 20 `catch`
  blocks with `unknown`). Then the rest of `translation/`.
- UI load baseline during a real run (Ashes, 2026-11-12, live page, 30-40 s windows):
  0 long tasks over 50 ms; 3.3 DOM mutations/s; 9-12 `/api/` requests per 30-40 s (queue,
  log, control, about every 10 s); API median 38-39 ms, one outlier 770-820 ms. After the
  `ui/html` helper in `renderSummary` and `renderEvents`: unchanged. Rule: no new polling;
  re-measure with the same script before changing render paths in `queue-manager`.
- Targeted repair (merged from `feat/chunk-quality-gates`; not wired into the pipeline): `src/literary/targeted_fix.py`
  repairs paragraphs of a finished EPUB that carry a forbidden glossary form or a blocking pt-PT
  form. Model call only for flagged paragraphs; accepted only when the failure is gone and the
  guard passes. Howling Dark (refined): 12 of 7,650 paragraphs flagged, 5 of them with inline
  markup (skipped). Run on a copy of the refined book (2026-11-12, guard v2, commit 235f908):
  7 attempted, 6 accepted, 1 rejected ("pagar" -> "construindo", a meaning error the v1 guard
  let through). Remaining flagged: 6, all in paragraphs with inline markup or the rejected one.
  No XHTML broke. Decided 2026-11-12: the six accepted changes are pt-BR word swaps (contacto,
  demónio, facto, prémio, Podia) and are now in the refined Howling file. The module stays out of
  the pipeline: it needs the model per paragraph, and its one trial rejection was a meaning error.
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
- Known defects: a resumed run can write a `(1)` duplicate; a job can stay
  `running` after a complete resume; the watchdog is monitor-only; UI reads still
  cross the bind mount (design §9).

## Open decisions

1. **Resolved 2026-11-12.** Kingdoms chapter 15: derived forms of a glossary target are data (`accepted_targets`; Legião accepts legionário(s)); `Sollan` used as an adjective is now sollana/sollano. The audit passes.
2. **Meaning gate (Howling).** Resolved 2026-11-12: Howling was approved by hand in the
   Queue UI and the gate is unchanged. Option 5 of `adjudicator-calibration-2026-11-11.md`
   (human review on any confirmed candidate) stays the recommendation; it needs a blind run first.
3. **Imperium vs Império.** The freeze is merged; Demon and Howling keep
   "Império" by owner decision.
4. **Per-book code still to move** (`docs/project/reviews/per-book-hacks-2026-11-12.md`):
   Howling sentence fixes and copyright line in `global_text_fixes`, the series
   Also-by string, `EN_RUNNING_HEADER`, and the Chantry metric in the Queue UI.
5. **Owner confirmations:** the "Scriptorium" name; upstream issue #333 is open.

## Model policy and evidence

- Local Index-Translate 9B for Sun Eater and Realm (Hy-MT2 Q4 as fallback).
  Cloud only when funded again. Evidence:
  `docs/project/reviews/sun-eater-model-selection-2026-11-10.md`,
  `docs/project/reviews/local-model-benchmark-2026-11-10.md`,
  `docs/project/reviews/local-model-ceiling-2026-11-12.md`.
- Balances (snapshot 2026-11-10): Anthropic US$ 1.54, DeepSeek US$ 1.38, Gemini
  exhausted. Ledger: `data/cost_ledger.jsonl`.

## Repository

- Branch `main`. Keep untracked user files out of commits (`.taste-skill/`,
  `Custom_Instructions/sun-eater-2.yaml`).
- Product name is Scriptorium; upstream credits, `tbl-*` EPUB ids, localStorage
  keys and `TBL_*` variables stay on purpose.
- Prompt library status: `docs/prompts/README.md` (top block).
