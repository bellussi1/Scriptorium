# Agent prompt library

Reusable prompts for the hardening work discussed on 2026-11-11. They are
proposals, not executed work: nothing here has been implemented or verified
unless a later commit says so.

Written in English to match the repository language policy; replies follow the
language of the conversation.

## Status (2026-11-12)

- Done and merged: 5.3 (baseline), 5.4 (single writer), 6.1 (inventory in
  `docs/project/reviews/per-book-hacks-2026-11-12.md`), 6.3 (checklist in
  `docs/project/onboarding-checklist.md`), 7.1–7.3 (`docs/project/reviews/local-model-ceiling-2026-11-12.md`).
- Done in code and checked: 1.4 (update check off by default, pointing at our own
  repository when enabled; User-Agent with the new name; no upstream Referer). 4.2
  (`scripts/auto_queue.py`: bounded restarts with backoff, gate hold, restart reason in
  the status file; `tests/literary/test_auto_supervisor.py` and `test_auto_queue_gate.py` pass).
- Done on branch `refactor/prompt-6-2-data`, not merged: 6.2. Book rules moved to
  `literary-resources` (`book_text_fixes`, `labels`, the Ship of Magic `running_header`);
  the Chantry metric became a count of forbidden forms. Demon in White's reader output is
  unchanged, except its four back-matter titles, which now have Portuguese labels.
- Edit prompts landed earlier: 1.3, 1.5, 2.2, 2.3, 3.2, 3.3 (see git log).
- Prepared, not run: 4.4 (24 h destructive window). Preflight, dedicated compose and runbook are in place
  (`docs/project/DESTRUCTIVE_24H_RUNBOOK.md`); the window phases and the soak are not written yet.
- Open: 3.4 waits for the owner's labels.
- Planning prompts with a written result in `docs/project/reviews/` (2026-11-12): 1.1 (fork-coupling-2026-11-12.md),
  1.2 (agpl-compliance-2026-11-12.md), 2.1 and 2.4 (status-diagnosis-2026-11-12.md), 3.1 (gate-coverage-2026-11-12.md),
  4.1 (failure-modes-2026-11-12.md), 4.3 (two-minute-review-design-2026-11-12.md), 5.1 (queue-db-write-map-2026-11-12.md).
  They are analysis and design only; none is implemented.

## How to use

- One prompt per session. Do not chain two prompts that both edit files.
- Run the planning prompts before letting any agent edit code; they are marked
  `plan` in the index below.
- Every prompt assumes the common preamble. Paste it at the start of the
  session or rely on `AGENTS.md`, which already carries most of it.

### Common preamble

```text
Read AGENTS.md and docs/ACTIVE_CONTEXT.md before acting. One book at a time,
one chunk at a time, do not start a translation, do not spend on cloud
providers without an explicit cap, do not push. Code, comments and docs in
English; answer in the language of the conversation.
```

## Index

| ID | Theme | Kind |
| --- | --- | --- |
| 1.1 | Fork coupling inventory | plan |
| 1.2 | AGPL compliance before rebranding | plan |
| 1.3 | Product identity, phase 1 | edit |
| 1.4 | Cut upstream network calls | edit |
| 1.5 | Docs and distribution | edit |
| 2.1 | Diagnose the lying status | plan |
| 2.2 | Canonical `queue status --json` | edit |
| 2.3 | Plugin consumes the canonical command | edit |
| 2.4 | Supervisor and status file map | plan |
| 3.1 | Real gate coverage | plan |
| 3.2 | Deterministic checks on 100% of files | edit |
| 3.3 | Regression golden set | edit |
| 3.4 | Calibrate the meaning gate | plan |
| 4.1 | Failure mode inventory | plan |
| 4.2 | Bounded supervisor auto-restart | edit |
| 4.3 | Two-minute review design | plan |
| 4.4 | 24 h destructive test | edit |
| 5.1 | Write map for `literary_queue.db` | plan |
| 5.2 | Single-writer intent design | plan |
| 5.3 | Baseline stress test | edit |
| 5.4 | Implement the single writer | edit |
| 6.1 | Per-book hack inventory | plan |
| 6.2 | Move per-book fixes into data | edit |
| 6.3 | New-book onboarding checklist | edit |
| 7.1 | Error taxonomy for the local model | plan |
| 7.2 | Refine return on investment | plan |
| 7.3 | Production scenario decision | plan |

---

## 1. Detaching from upstream without becoming an orphan clone

### 1.1 Fork coupling inventory (plan)

```text
Do a read-only inventory of how this repository is coupled to the upstream
hydropix/TranslateBooksWithLLMs. Scan code, docs, configuration, Docker/CI,
locales and EPUB metadata. For each item record path:line, type (product name,
URL, authorship credit, technical dependency, telemetry/update check) and
whether it can be changed without breaking behaviour. Include at least
src/config.py, src/utils/version_checker.py, src/core/llm/base.py,
src/core/llm/providers/openrouter.py, src/literary/kindle.py, README.md and
docs/DOCKER.md. Do not edit, do not run a translation, do not make network
calls. Deliver the table plus a five-line summary: what is identity, what is a
legal obligation, what is a real dependency.
```

### 1.2 AGPL compliance before rebranding (plan)

```text
Before any rebranding, audit this fork's compliance with AGPL-3.0. List what
the licence requires preserving (LICENSE, copyright notices, identification of
modifications, source-code offer) and what is free to change (product name, UI,
documentation, images). Check the current state in LICENSE, file headers,
README, EPUB metadata and Docker images. Point out gaps with path:line. Do not
edit and do not give a definitive legal opinion; deliver a technical checklist
and the items that need a human decision.
```

### 1.3 Product identity, phase 1 (edit)

```text
Implement phase 1 of the rebranding: product identity, without touching the
licence or credits. Change the displayed name in src/config.py
(GENERATOR_NAME/GENERATOR_SOURCE), the translator field in
src/literary/kindle.py, titles and strings in src/web/templates and
src/web/static/locales/{pt-BR,en}, and the README header. Keep LICENSE, the
fork notice and the link to the upstream. Do not rename the remote repository,
do not push, do not touch literary_queue.db or translated text. Run
pytest -q tests/unit tests/literary and the i18n suite; report the real result.
```

### 1.4 Cut upstream network calls (edit)

```text
Cut the network calls that still point at the upstream. Today
src/utils/version_checker.py queries the hydropix release API,
src/core/llm/base.py sends a User-Agent with the old name, and
src/core/llm/providers/openrouter.py sends the original project's
HTTP-Referer/X-Title. Implement the conservative option: update check off by
default (or pointing at our own repository when enabled), User-Agent with the
new name, no upstream Referer. No network calls in tests; use mocks. Run the
relevant suite and show the diff.
```

### 1.5 Docs and distribution (edit)

```text
Rewrite the installation and distribution story for the fork. README and
docs/DOCKER.md currently tell people to download upstream releases and
ghcr.io/hydropix images. Replace that with a local build from source, using the
real commands in this repository (docker-compose.dev.yml, translate.py,
launcher.py). Remove upstream download badges and links, keep attribution and
the licence. Do not publish an image, release or package. Deliver the changed
files and the commands you actually ran.
```

---

## 2. Status and a single source of truth

### 2.1 Diagnose the lying status (plan)

```text
Diagnose the inconsistent project status. Symptom: literary_status and the
injected block say "next #11 Kingdoms of Death" while Demon in White is
translating. Read .opencode/plugins/literary-context/index.ts in its current
state (it is being edited), data/literary_queue.{agent,runner,auto,health,
control}.json, and the real state via python -m src.literary.cli queue
list/jobs. Explain the data lineage with timestamps and why "next" is not
"running". List every consumer of that state (plugin, API, UI, supervisor). Do
not edit. Deliver the diagnosis and where the truth should come from.
```

### 2.2 Canonical `queue status --json` (edit)

```text
Create the single source of truth for status: python -m src.literary.cli queue
status --json. It must read literary_queue.db (not the JSON caches) and return,
with a versioned schema: running (bool), book {id,title,state}, job
{id,translation_id}, progress {chunks,total,percent,rate,eta}, heartbeat_age_s,
stale (bool), next_pending, blockers, db {integrity,journal_mode}, snapshot_at.
Read-only, short timeout, no writes to disk. Add tests under tests/literary
covering: book running, runner stopped, DB missing, stale heartbeat. Do not
touch the plugin yet.
```

### 2.3 Plugin consumes the canonical command (edit)

```text
Make the literary-context plugin consume only the canonical queue status
--json command, with a timeout and an explicit fallback. Rules: running and
next are separate fields and never get mixed; if the command fails, the block
says "status unavailable" with the age of the last known data and never infers
from runner.json; the literary_status tool and the injected block show the same
state. Remove redundant JSON reads. Test manually with Demon in White running:
the status must name Demon, not Kingdoms of Death. Show the output before and
after.
```

### 2.4 Supervisor and status file map (plan)

```text
Map the supervisors and status files: scripts/auto_queue.py,
scripts/queue_runner_agent.py, scripts/watch_translation.py,
data/literary_queue.{auto,agent,runner,health,control}.json and what the UI
reads. For each process: who starts it, what it writes, how often, and what
happens if it dies. Identify which one is authoritative and which are caches.
Propose the target design with one supervisor and one status, and say what
dies. Plan only, do not implement.
```

---

## 3. Deterministic gate with coverage

### 3.1 Real gate coverage (plan)

```text
Measure the real coverage of the quality gate. For scripts/audit_book.py and
scripts/intra_run_audit.py, list every detector, whether it runs on a sample or
on 100% of the files, its cost, and the known false negative (TIVAMOS NOSSO
CARON in chapter 24, CHANTRY on the chapter 76 dropcap). Produce a matrix of
detector x coverage x cost x case that escaped. State explicitly what fraction
of Howling Dark's 94 files was inspected in the last round. Do not edit and do
not call the cloud.
```

### 3.2 Deterministic checks on 100% of files (edit)

```text
Make the deterministic checks run on 100% of the XHTML files, not on a sample:
forbidden renderings, glossary adherence, pt-PT, English leakage, repetition,
per-file length ratio, and all-caps/dropcap. The report must be per file, with
top offenders, and the gate must aggregate without diluting a local error. No
cloud calls. Measure the total runtime on Howling Dark and show the coverage
matrix before and after.
```

### 3.3 Regression golden set (edit)

```text
Build a golden set from the real defects: TIVAMOS NOSSO CARON (chapter 24,
expected TÍNHAMOS NOSSO CARONTE), CHANTRY on the chapter 76 dropcap (expected
CHANTRIA), and the Caron/Vesperad cases. Put small fixtures under
tests/literary/fixtures with the broken and the corrected text, one test per
violated rule, and make sure the test fails on the old text and passes on the
new one. Each fixture references the chapter and the rule. Run pytest and show
the output.
```

### 3.4 Calibrate the meaning gate (plan)

```text
The meaning gate is blocking Howling Dark with 2 confirmed candidates that a
manual read says are false positives (uptown -> "lá em cima", glad -> "grato").
Measure the adjudicator's false-positive rate on a sample I will label, propose
the adjustment (threshold, second adjudicator, tie-break rule, or mandatory
human review) and show the numbers in a table. Do not change the gate and do
not reprocess the book without my decision.
```

---

## 4. 24/7 autonomy

### 4.1 Failure mode inventory (plan)

```text
List the failure modes that break 24/7 operation so far: supervisor stopped,
gate blocking, stale status, corrupted jobs.db, app restart, pause-now, resume
duplicating an EPUB. For each: how it is detected today, how it recovers today,
time until human intervention, and whether it depends on someone watching.
Base it on docs/ACTIVE_CONTEXT.md, docs/project/DESTRUCTIVE_TESTS.md and the
logs. Deliver the table and the three most expensive bottlenecks.
```

### 4.2 Bounded supervisor auto-restart (edit)

```text
Implement supervisor auto-restart with bounds. scripts/auto_queue.py must be
restarted when the process dies or the heartbeat passes the limit, with
exponential backoff, at most N attempts per hour, and never when the reason is
needs_review (gate) — in that case only notify. The restart reason goes into
the canonical status. Test with a simulated kill and with a gate failure; show
the log for both situations.
```

### 4.3 Two-minute review design (plan)

```text
Design the two-minute review. A human must approve or reject a book without
opening a terminal: 5 side-by-side passages (source and translation), terms
outside the glossary, confirmed meaning errors, gate metrics, and an
approve/reject button with a reason. Propose the screen, the endpoint and how
the decision is recorded in the audit. Do not implement yet; deliver a textual
wireframe and the API contract.
```

### 4.4 24 h destructive test (edit)

```text
Write the 24 h destructive test in a controlled environment: kill the process
mid-run, corrupt the DB, pause, resume, restart the app, and resume with the
target EPUB already present. Criteria: no book advances state without a
checkpoint, no duplicate file with a (1) suffix, no job stuck in running after
completion. Run whatever is safe now and deliver the report with what still
needs a window.
```

---

## 5. Concurrency and the single writer

### 5.1 Write map for `literary_queue.db` (plan)

```text
Map every write to data/literary_queue.db: files and functions, who writes
(Flask app, CLI, host runner), transaction type, timeout, journal mode, and what
happens under concurrency. Include the approve/retry/add/move/remove endpoints
in src/api/blueprints/literary_queue_routes.py. Classify each write by
lock/corruption risk. Do not edit. Deliver the map and the three most dangerous
points.
```

### 5.2 Single-writer intent design (plan)

```text
Design the single-writer refactor for literary_queue.db. The app stops writing
directly and emits intents (approve, retry, add, move, remove) into a table with
id, kind, payload, created_at, applied_at, error; only the host runner applies
them, in order, idempotently. Define the schema, the migration, what happens
when the runner is stopped, and UI compatibility. Detailed plan, no code.
```

### 5.3 Baseline stress test (edit)

```text
Before refactoring, write the test that reproduces the problem: while a book is
translating, fire 100 approve/retry/add/move/remove operations through the API
and check for database is locked, the 30 s timeout, and inconsistent state. Run
it against the current code, record the failure rate and attach the log. This
is the baseline the single writer has to zero out.
```

### 5.4 Implement the single writer (edit)

```text
Implement the intent queue and the single writer according to the approved
plan. The app only enqueues, the runner applies, the UI reads the result. Keep
journal DELETE, busy_timeout and a compatible migration. Done when the 100
operation stress test passes without locks or inconsistent state, and
pytest -q tests/unit tests/literary is green.
```

---

## 6. Generalisation (anti-overfitting)

### 6.1 Per-book hack inventory (plan)

```text
List every book-specific hack in code and resources: hardcoded Howling Dark
fixes, Chantry/Caron/Vesperad, dropcap cases, per-title exceptions. For each:
where it lives, why it exists, and a classification — (a) becomes
glossary/data, (b) becomes a general rule, (c) remove. Deliver the table and
what still prevents the next book from running without a patch.
```

### 6.2 Move per-book fixes into data (edit)

```text
Move book-specific fixes into data. Every term variant must live in
literary-resources (compiled into data/compiled), with aliases and forbidden
forms, not in code. Remove the hacks classified as (a) and (b). Note:
data/glossaries.db is a UI copy, not the runtime source. Done when Demon in
White runs with its own glossary and no per-title condition. Show the diff and
the tests.
```

### 6.3 New-book onboarding checklist (edit)

```text
Create the onboarding checklist for a new book: compiled and validated
glossary, official terms checked, style block, aliases/forbidden, gates, audit
sample and acceptance criteria. Run the checklist on Kingdoms of Death in dry
mode (no translation) and report what is missing. This is the test that the
pipeline generalises.
```

---

## 7. Local model ceiling

### 7.1 Error taxonomy for the local model (plan)

```text
Classify Index-Translate 9B errors in Howling Dark by type: calque, idiom,
omission, register, syntax, proper noun. Use the audits and a chapter sample;
give examples and frequency. Separate what the refine pass fixes from what it
does not. Deliver the taxonomy and a conclusion about the real ceiling of the
local model.
```

### 7.2 Refine return on investment (plan)

```text
Measure the return of the ~4 h refine per book. Compare the same audited sample
before and after refine (prose, fidelity, naturalness, meaning errors), with
cost in hours and gain per dimension. Say which kinds of book benefit and which
do not. Numbers, not impressions.
```

### 7.3 Production scenario decision (plan)

```text
Using the ceiling and refine numbers, build three production scenarios: local
only, local plus full refine, and hybrid (local with Haiku/Gemini only on
flagged passages). For each: cost per book, time, expected quality and risk.
Recommend one and state what would have to be true to change scenario. Do not
implement.
```

---

## Suggested order

1. `1.1 -> 1.2 -> 1.3`: identity without breaking the licence.
2. `2.1 -> 2.2 -> 2.3`: status before any new UI.
3. `3.1 -> 3.2 -> 3.3`: close the gate blind spot.
4. `5.3 -> 5.4`: prove the problem before refactoring.

Run the `plan` prompts before letting an agent edit files. Each `edit` prompt
ends with a verification command; treat its real output as the acceptance
evidence, not the agent's summary.
