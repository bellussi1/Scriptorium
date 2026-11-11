# Active context

Handoff between sessions. Read this first; update it before you stop. This file
is the shared state for both Claude Code and OpenCode, so it must describe the
real repository, not a plan.

Status: current as of 2026-11-10. Revalidate with `git status` and `git log`
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
- **Howling Dark is now a fresh run**: job 20, `cli_bc71db89`, **3/1074
  chunks** at 02:36 UTC, no malformed errors. The auto supervisor (pid 9528)
  is running the queue directly; the host queue agent is dead. One pass,
  refinement disabled.
- Main app on `:5000`, preview on `:5001`.
- The Translate tab now mirrors the active queue book: title, progress, ETA,
  last log line and a 30-line activity log. The panel is created dynamically so
  it works with the cached template and does not stop the translation. The
  quality/log drawer was moved to the document body so it opens from either
  tab. The static template also carries the panel for the next restart.

## Translation state

- **Sun Eater books 2-7 are now `ollama` / Index-Translate 9B**, one book at a
  time. Howling Dark is first. Its old Hy-MT2 output is archived at
  `translated_files/archive/howling-dark-hy-mt2-2026-11-10/`.
- Howling Dark is now job 20 (`cli_bc71db89`), a fresh run after the jobs.db
  corruption. The interrupted partial EPUB is archived at
  `translated_files/archive/howling-dark-partial-2026-11-11/`; the old upload
  `data/uploads/cli_c6f4be29` is backed up as `.bak-2026-11-11`. Job 19 was
  cleared so no stale checkpoint can be mixed into the new run.
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

- `scripts/auto_queue.py` (pid 40576) waits for Howling Dark. At the gate it
  runs `scripts/audit_book.py`; on a full pass it approves, exports Kindle and
  starts the next pending book. Any failure stops and leaves `needs_review`.
- Gates: queue validation/EPUBCheck; glossary coverage >= 0.90 and zero
  forbidden renderings; pt-PT <= 50 per 100k; English leakage <= 0.01;
  repetition <= 0.05; length ratio 0.80-1.20; Haiku sample audit with
  fidelity/naturalness >= 3.5 and at most one meaning error.
- Caps: **US$ 0.05 per book**, **US$ 0.50 total**; model `claude-haiku-5-5`
  with thinking disabled. Audit rows use `stage: auto-audit` in the ledger.
- Calibration on the archived Hy-MT2 Howling Dark: coverage 0.977; it fails
  only on the forbidden `Chantry` (the old output uses Chantry instead of
  Chantria). The Extrasolarian change is recorded as glossary drift and
  excluded from the hard gate because the run saw the old target. Cloud test:
  six meaning errors, cost US$ 0.0008.
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
