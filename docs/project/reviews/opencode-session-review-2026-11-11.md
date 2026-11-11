# OpenCode session review (2026-11-11)

Scope: the OpenCode session that built the literary pipeline between
2026-11-07 and 2026-11-11, what it implemented and what it did not, how it
worked, and the state it left behind. Facts come from the OpenCode database
(read from a copy, session `ses_e4825d7f0ffetd0fdMu5zWkr1m`), `git log`, the
queue database and the audit artefacts. Nothing here is a claim that was not
checked against one of those sources.

## 1. The session

- Main session "Sistema de tradução literária EN–PT-BR": 7,495 messages, 152
  user turns, 2026-11-07 18:11 → 2026-11-11 17:07 local. It ended as
  `interrupted` in the middle of an edit (turn 152, prompt 5.3).
- Sub-sessions: "Editorial style profiles" (eight profiles, marked provisional
  where evidence was missing), "Translate UI locales" parts 1 and 2,
  "Dalibre and Kindle library setup", "Desvincular o fork do projeto original".
- Main session tool use: 4,635 shell calls, 1,988 edits, 812 reads, 464
  writes, 337 pytest invocations, 156 `git commit` invocations.
- Git since 2026-11-07: 162 commits, all under the owner's identity, one with
  a Co-Authored-By trailer.

## 2. How OpenCode worked

Replies
- Portuguese, result first, tables for numbers, and explicit scope statements
  ("nada implementado", "não alterei o gate", "sem nuvem", "a fila viva não foi
  tocada"). For the risky items it stopped and asked (cloud spend, live DB,
  upstream PRs).
- Read-only prompts (`plan`) were answered without editing; edit prompts were
  committed separately.
- Weak spots: some answers were never saved to the repository (see §3), one
  answer is missing entirely (5.2), and the status documents contradict each
  other (see §5).

Coding
- Small, focused commits with Conventional Commits subjects in English and
  explanatory bodies (for example `6f71f53 feat(queue): auto-restart the
  supervisor with limits`).
- Docs were updated in many commits (`docs/project/POC.md`, `AUDIT.md`,
  `ACTIVE_CONTEXT.md`); this is the main source of churn and of drift.
- Live state was protected: scratch databases for destructive tests, a
  separate `jobs.mirror.db` for host reads, snapshots before risky steps.

Tests
- Unit and literary suites: 2,936 → 2,955 → 2,968 tests recorded in the commit
  history; `ACTIVE_CONTEXT.md` reports 2,345 passed plus one environment
  failure (`test_path_validator`, a Linux backslash path). See §6 for the run
  made during this review.
- EPUBCheck, `ebook-meta` and reader checks after EPUB changes; a golden set
  built from the defects that escaped (3.3).

Commits and remotes
- Two fix branches were pushed to `origin` and two upstream PRs were opened
  (#334, #335) against the original project. On 2026-11-08 the owner decided to
  stop proposing anything upstream. As checked on 2026-11-11, issues #331 and
  #332 and PRs #334 and #335 are closed; issue #333 is still open.

## 3. Prompt library (`docs/prompts/README.md`)

Implemented and committed

| Prompt | Commit | Note |
| --- | --- | --- |
| 1.3 Product identity, phase 1 | `7aaf460` | Working name "Scriptorium"; the owner must confirm the name (four strings). |
| 1.4 Cut upstream network calls | `fe1f6d5` | Update check off by default; no upstream headers. |
| 1.5 Docs and distribution | `ea7c1a6` | Local build instructions. |
| 2.2 Canonical `queue status --json` | `91f5289` | Read-only; reads `literary_queue.db`. |
| 2.3 Plugin reads the canonical status | `6ee1cc2` | The "Demon running" manual check the prompt asked for is not recorded. |
| 3.2 Deterministic checks on 100% of files | `6b19964` | Per-file gates. Source of the current Demon in White FAIL (§5). |
| 3.3 Regression golden set | `c2a7fbc` | Fixtures for the CARON and CHANTRY defects. |
| 3.4 Calibrate the meaning gate | `4937fd7` | Measurement only. The owner must label the sample; the decision is open. |
| 4.2 Bounded supervisor auto-restart | `6f71f53` | Tested with a fake worker on a scratch DB; not yet run by the live supervisor. |
| 4.4 24 h destructive test | `ada0fc6` | Rehearsal only; three FAILs (§4). The 24 h window has not run. |
| Prompt library | `4c15157` | — |

Answered in chat only (not saved in the repository)

- 1.1 fork coupling inventory; 1.2 AGPL checklist (explicitly not a legal
  opinion); 2.1 diagnosis of the stale status (root cause: the plugin read an
  old `agent.json`; addressed by 2.2 and 2.3); 2.4 supervisor and status map;
  3.1 real gate coverage; 4.1 failure-mode inventory; 4.3 two-minute review
  wireframe; 5.1 write map of `literary_queue.db`.
- 5.1 was pasted twice (user messages 149 and 151); one answer was given.

Not answered or not started

- 5.2 single-writer design: the reply to turn 150 has no text at all.
- 5.3 baseline stress test: two files were written and never run or committed
  (`tests/standalone/concurrency_baseline.py`, 1,031 lines;
  `tests/standalone/concurrency_writer.py`, 191 lines). The last edit was
  aborted at 17:07 local.
- 5.4 single writer; 6.1 per-book hack inventory; 6.2 move per-book fixes into
  data; 6.3 onboarding checklist; 7.1 error taxonomy; 7.2 refine return on
  investment; 7.3 production scenarios.

## 4. Other open items

| Item | State |
| --- | --- |
| Destructive 24 h test | Three FAILs in the rehearsal (`docs/project/reviews/destructive-24h-2026-11-11.md`): a resume writes a `(1)` duplicate; a job stays `running` after completion; the 24 h run needs a window. |
| Watchdog auto-restart | Not implemented (monitor only). |
| Single writer for `literary_queue.db` | Not implemented (5.2 to 5.4). |
| Glossary UI copy `data/glossaries.db` | Still on the bind mount with WAL; not the runtime source. |
| Meaning gate | Open decision: approve manually, add a stronger adjudicator, or raise the threshold to 2. The owner's sample labels are needed. |
| RotE | Ship of Magic and Fool's Errand were translated with Hy-MT2 and should be redone with Index; three pending RotE rows (Ship of Destiny, The Golden Fool, Fool's Fate) still carry Hy-MT2. |
| Malazan | Ten split EPUBs are queued with no glossary or style (zero terms). |
| Lonesome Dove | Not in the queue. Resources exist (`literary-resources/larry-mcmurtry/lonesome-dove/`). The owner's own PT translation is not official and is not a reference. |
| Scriptorium name | Needs owner confirmation. |

## 5. Quality review of the two translated books

Howling Dark (book 10, job 21): audit PASS. Report:
`data/audits/review-20261111-howling-dark/audit.md`.
- Glossary coverage 0.9935 (153/154), forbidden 0, pt-PT 13.86 per 100k,
  English leakage 0.0002, repetition 0, length ratio 1.0046.
- Cloud sample (Haiku, 7 passages): prose 4.0, fidelity 4.0, meaning 0 confirmed,
  tense 0, gender 0.

Demon in White (book 8, job 23): audit FAIL. Report:
`data/audits/review-20261111-demon-in-white/audit.md`. Three per-file reasons:
1. Forbidden rendering: `OEBPS/xhtml/96_Lexicon.xhtml` keeps the English headword
   "Chantry" (glossary target "Chantria"). Real defect.
2. Length ratio 0.343 in `OEBPS/9780756413088_nav.xhtml` (130 words against 379).
   The navigation lists "CAPÍTULO n" with no titles, and the chapter `<title>`
   elements are still English ("Chapter 1: Behold a Pale Horse, Demon in
   White"). Real defect for KOReader navigation.
3. Glossary coverage 0.7647 in `OEBPS/xhtml/22_Chapter_16_Other_Devi.xhtml`.
   I checked two of the four misses: the text contains "Imperador" and
   "Quieto", and "Legiões" (plural) is counted as a miss for "Legião". The
   matcher does not handle inflected forms. False positive, and a gate bug.

Other findings for Demon in White
- Its OPF has no series metadata (`belongs-to-collection`). The series post-pass
  was only applied to Howling Dark.
- Its navigation has no translated chapter titles because Howling Dark's titles
  come from glossary entries (for example "The Red Company" →
  "A Companhia Vermelha"). Demon has no such entries. Each new book needs its
  chapter titles in data.
- Cloud sample: prose 4.0, fidelity 4.125, meaning 0 confirmed (two candidates
  not confirmed), tense 0, gender 1 (gate allows at most 1).

Approval record
- Both books were approved from the Queue UI at 15:52 UTC (12:52 local), event
  text "human review approved from Queue UI". OpenCode did not approve them and
  noticed the change at 12:55 local.
- Demon in White was approved without a passing audit (no audit had been run
  for it). Howling Dark was approved while its audit was blocked on two
  meaning notes that the manual read judged false positives.

### Owner decision on the Imperium drift (2026-11-11)

- The owner accepted the `Imperium` drift for Demon in White. The book keeps
  "Império" from its compiled glossary snapshot; the freeze does not apply to it.
- Post-pass applied afterwards (`src/literary/chapter_titles.py`): 87 chapter
  titles, the Lexicon headword and the series metadata; EPUBCheck 0/0/0. Backup:
  `translated_files/Demon in White (pt-BR).refined.pre-review.epub`.
- The re-audit (`data/audits/review-20261111-demon-in-white-post/audit.md`) is
  still FAIL for the chapter 22 coverage false positive. That item is open:
  changing the matcher changes the gate for every book, so it needs the owner's go-ahead.

## 6. Checks run during this review

- Test suite `pytest -q tests/unit tests/literary` on the merged tree: 2,411
  passed, exit 0 (`venv` with `requirements-dev.txt`; pytest was not installed
  in the venv before this review).
- Freeze branch `glossary/terminology-freeze` (commit `acae484`) merged into
  `main` after a clean test-merge. `resources validate`: 39 files, passed.
  `tests/literary/test_terminology_freeze.py`: 3 passed.
- App container rebuilt and restarted (`docker compose -f docker-compose.dev.yml
  up -d --build app`); healthy; `http://127.0.0.1:5000/` returns 200.
- Kingdoms of Death (book 11, job 24) started on the queue with `queue run
  --book-id 11 --parallel 1`; it stops at `needs_review` by design. Model
  Index-Translate 9B, 862 chunks.

## 7. Recommended order for the rest

1. Demon in White: fix the Lexicon headword, add translated chapter titles as
   book data, add the series metadata, re-run EPUBCheck and the audit.
2. 5.3 baseline stress test on a scratch DB, then 5.4 single writer on a
   branch, merged only after the Kingdoms run ends.
3. Queue Lonesome Dove after Sun Eater (priority between Shadows Upon Time and
   The Mad Ship), then RotE (redo Ship of Magic and Fool's Errand with Index),
   then Malazan once its glossary is built.
4. Prompts 6.1 to 7.3, one at a time, each with its own commit.
