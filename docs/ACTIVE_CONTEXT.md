# Active context

Handoff between sessions. Read this first; update it before you stop. This file
is the shared state for both Claude Code and OpenCode, so it must describe the
real repository, not a plan.

Status: current as of 2026-11-10. Revalidate with `git status` and `git log`
before acting on anything below.

## Repository

- Branch `main`; the local benchmark report and adapters are committed in
  `ae75dc5`; the OpenCode skills/plugin/ledger are in `d19b42f`.
- Working tree keeps the user's untracked `AGENTS.md`, `.taste-skill/` and
  `Custom_Instructions/sun-eater-2.yaml`.
- Nothing has been pushed.

## Runtime

- Queue agent: online, fresh heartbeat, **runner active**.
- **Demon in White** is translating with Gemini 3.8 Flash, job 17,
  `cli_7182b270`, **283/1184 chunks** in the translation log at 19:11 UTC (the
  queue DB still reports 208 because the sync lags chapter boundaries).
- Rate: about 1.43 chunks/min since 15:54 UTC; total ETA about 13.8 h, roughly
  10.5 h remaining. This is an extrapolation, not a guarantee.
- Main app on `:5000`, preview on `:5001`.

## Translation state

- **Demon in White**: provider `gemini`, model `gemini-3.8-flash`, status
  `translating`, job 17. The previous Haiku attempt stopped at 137/1184; its
  checkpoint was discarded to avoid mixing models. Job 16 failed with
  `output EPUB was not created`; job 17 is the current run.
- No other book will start until this one stops at the review gate.
- DeepSeek balance: **US$ 1.38** (untouched). Claude balance: **US$ 2.47**.
  Gemini: **R$ 30 credit + R$ 61 monthly GCP** (R$ 91 total).
- Ledger: Gemini **US$ 1.32** historical (US$ 0.275 benchmarks + US$ 1.044
  queue partial at 283/1184, estimated); Claude **US$ 0.57** historical
  (US$ 0.38 dev judge + US$ 0.08 test judge, both estimated, plus US$ 0.105
  Haiku partial). `scripts/lit_queue_cost.py` upserts the running job estimate
  and reads the queue log when the DB progress lags.
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

**Sun Eater primary: Gemini 3.8 Flash.** The R$ 91 budget covers roughly the
next three books (Demon in White ~US$ 4.4, Kingdoms of Death ~US$ 3.1, Ashes of
Man ~US$ 3.1). Haiku 5.5 is the cheaper cloud fallback for the last two books;
Index 9B is the free local fallback. Realm of the Elderlings stays on Index.

## Next decision

*Demon in White* is already running with Gemini under the R$ 91 cap. Monitor it
to the review gate; do not start another book until it stops. After the gate,
review the EPUB (EPUBCheck and TOC), approve, and then decide whether
*Kingdoms of Death* follows on Gemini.

Local benchmark: the native EuroLLM prompt and the 28-pair test split are done;
the provisional Index decision stands. Optional fair check: rerun EuroLLM with
the 2,228-character style block before treating the local gap as final.
Dalibre: restart OpenCode so the MCP reconnects with `DALIBRE_TOKEN`.
