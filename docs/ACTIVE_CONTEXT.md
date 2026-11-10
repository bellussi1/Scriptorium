# Active context

Handoff between sessions. Read this first; update it before you stop. This file
is the shared state for both Claude Code and OpenCode, so it must describe the
real repository, not a plan.

Status: current as of 2026-11-10. Revalidate with `git status` and `git log`
before acting on anything below.

## Repository

- Branch `main`; the Sun Eater benchmark work is committed through `4e2f7df`
  (Gemini decision, Claude judge runner, project README and this file).
- Working tree has two untracked user items: `.taste-skill/` and
  `Custom_Instructions/sun-eater-2.yaml`.
- Nothing has been pushed.

## Runtime

- Queue agent: online, fresh heartbeat, idle.
- Runner: none active. No translation is running.
- Main app on `:5000`, preview on `:5001`.
- No cloud request is active.

## Translation state

- **Demon in White** is paused, provider `ollama`, model **Index-Translate 9B**.
- The previous Haiku attempt stopped at 137/1184 chunks; its checkpoint was
  discarded from the queue to avoid mixing models. The partial upstream upload
  remains orphaned.
- The queue is not resumed automatically; starting it is a human decision.
- DeepSeek balance: **US$ 1.38** (untouched). Claude balance: **US$ 2.47**.
  Gemini: **R$ 30 credit + R$ 61 monthly GCP** (R$ 91 total).
- Estimated new spend this round: Gemini ~US$ 0.31; Claude Sonnet judge ~US$ 0.40.
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

## Local benchmark finished (Claude Code session, 2026-11-10 10:45–11:17)

- Qwen3 8B, EuroLLM-9B and SalamandraTA-7B ran on the Sun Eater dev (56),
  probes (50) and test (28) corpora, same 73-form prompt, one repeat. Output:
  `data/benchmark/eval-sun-eater-{dev,probes,test}-v3-local/`. The GPU is free.
- chrF dev / test: EuroLLM 0.6785 / 0.6804, Salamandra 0.6559 / 0.6796, Qwen3
  0.6495 / 0.6581. Index stays ahead (0.6876 / 0.6947). Probe terms: Qwen3
  1.0, EuroLLM 0.9829, Salamandra 0.906 (repetition 0.119 on dev, length ratio
  1.13). Single repeat.
- Blind A/B on dev (56), one AI judge (subagent), no human check: Index beats
  Qwen3 42–11–3 (p < 0.0001) and EuroLLM 36–19–1 (p = 0.03; Index decisive win
  rate 65.5%, CI 52.7–78.2%). Index stays the local default; EuroLLM is the
  only close challenger and it loses on dialogue (1–7). Test split not judged.
  Files: `data/benchmark/sun-eater-dev-local-index-vs-{eurollm-9b,qwen3-8b}/`.
- `benchmark/literary/adapters.py` (uncommitted) registers `eurollm-9b` and
  `salamandrata-7b` with a new `colon_translate` prompt style. The generic system
  prompt made Salamandra echo the instructions (chrF 0.34). The new format is
  from memory of the model cards and is not verified.
- Next: score probes for the three new runs (`scripts/score_probes.py`), compare
  against Index, then decide whether any local model challenges Index for
  Realm of the Elderlings. Expect pt-PT bias from EuroLLM and Salamandra.

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
  prints the report.
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

Start *Demon in White* with Gemini under a hard R$ 91 cap, or keep it local
with Index. Do not start either without confirming with the user. The queue
review gate remains mandatory; cloud drafts skip the Ollama refinement pass.
