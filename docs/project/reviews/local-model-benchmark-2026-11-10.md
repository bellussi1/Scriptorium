# Local model benchmark: EuroLLM, Salamandra, Qwen3 vs Index (2026-11-10)

Question: does any local model beat Index-Translate 9B for English to Brazilian
Portuguese literary translation on the 8 GB card? Companion to
`sun-eater-model-selection-2026-11-10.md`, which covers the paid models.

## Setup

- Corpus: Sun Eater, *Empire of Silence*, dev 56 / probes 50 / test 28, official
  PT-BR reference. Same 73-form glossary as the paid round. Index and Hy-MT2
  also received the 2,228-character style block; the colon-style runs (EuroLLM,
  Salamandra) received only the glossary. That asymmetry favors Index, so the
  gap is if anything overstated; it is recorded in the caveats.
- Models run here, one repeat each, Ollama on the host, Q4_K_M:
  Qwen3 8B, EuroLLM-9B (community GGUF), SalamandraTA-7B (BSC-LT GGUF).
  Index-Translate 9B and Hy-MT2 Q4 are reused from the earlier v2 runs on the
  same corpus and prompt.
- Output: `data/benchmark/eval-sun-eater-{dev,probes,test}-v3-local/`.
- Code: `benchmark/literary/adapters.py` registers `eurollm-9b` and
  `salamandrata-7b` with the controlled `colon_translate` style
  (`Translate ... from English into Brazilian Portuguese.\nEnglish: ...\nPortuguese:`).
  The official EuroLLM template was verified on 2026-11-10 against the public
  EuroLLM-1.7B-Instruct card (the 9B card is gated but uses the same template):
  `Translate the following English source text to Portuguese:\nEnglish: ... \nPortuguese:`.
  The controlled prompt is a deliberate adaptation: it names Brazilian
  Portuguese and prepends the glossary. `eurollm-9b-native` repeats the round
  with the official sentence structure to test whether the wording matters.
  The generic system prompt made Salamandra translate the instructions instead
  of the text (chrF 0.34 on a 3-excerpt smoke test), so it is not a fair prompt
  for either model. Salamandra's native template was not independently verified.

## Results

| Model | Dev chrF | Test chrF | Dev names | Probe terms | Dev repetition |
|---|---:|---:|---:|---:|---:|
| Index 9B | **0.6876** | **0.6947** | 0.9626 | 0.9915 | n/a |
| EuroLLM-9B (controlled) | 0.6785 | 0.6804 | 0.9461 | 0.9829 | 0.014 |
| EuroLLM-9B (native prompt) | 0.6781 | 0.6793 | 0.9461 | 0.9744 | 0.014 |
| Hy-MT2 Q4 | 0.6670 | 0.6580 | 0.9427 | 0.9744 | n/a |
| Qwen3 8B | 0.6495 | 0.6581 | 0.9495 | **1.0** | 0.014 |
| SalamandraTA-7B | 0.6559 | 0.6796 | 0.9009 | 0.906 | 0.119 |

Latency is 4 to 5 s p50 per excerpt for all of them, with the GPU free.
Salamandra has a length ratio of 1.13 on dev and misses 8 probes, so it was
not judged.

The official EuroLLM sentence structure is a wash: dev chrF 0.6781 vs 0.6785,
test 0.6793 vs 0.6804, probe terms 0.9744 vs 0.9829, probe names 1.0, zero
swaps.
It changes neither the ranking nor the prose verdict; the controlled colon
prompt stands. The full native run is in
`data/benchmark/eval-sun-eater-{dev,probes,test}-v5-eurollm-native/`; a
14-excerpt paired sample was identical at 0.6807 mean chrF for both wordings.

## Blind A/B (key-normalized to Index)

| Split | Pair | Index | Other | Ties | Sign test | Index decisive win rate (95% CI) |
|---|---|---:|---:|---:|---:|---|
| dev (56) | Index vs EuroLLM | 36 | 19 | 1 | p = 0.03 | 65.5% (52.7-78.2) |
| test (28) | Index vs EuroLLM | 22 | 4 | 2 | p = 0.0005 | 84.6% (69.6-96.3) |
| dev (56) | Index vs Qwen3 | 42 | 11 | 3 | p < 0.0001 | 79.3% (67.9-89.3) |

On dev, Index leads EuroLLM in every category except action (3-5); the gap is
widest in dialogue (7-1) and terminology (6-2). On test, Index wins every
category except irony (1-2-1); the largest gaps are long syntax (4-0),
introspection (4-0) and dialogue (4-0), and the six non-wins are mostly pt-PT
forms or terminology slips in the Index output, not EuroLLM superiority on
prose.

Judges: one subagent per pair for dev, Claude Sonnet for test, reading only the
anonymized batches and never the key. Same kind of single AI judge as the
earlier A/B rounds, not a professional reviewer. The test judgments used two
batches of 14 pairs; the key was applied only after judging.

Human check: 15 blind Index-vs-EuroLLM pairs, 2 per category (3 description).
The owner agreed with the judge on **14 of 15**; the owner picked Index 9 times
and EuroLLM 6 times, the judge Index 10 times. Fifteen pairs calibrate the
judge but do not prove the 56-pair result by themselves.

## Decision

- **Local default stays Index-Translate 9B**, for Sun Eater fallback and for
  Realm of the Elderlings.
- The 28-pair test A/B confirms the dev result: Index 22-4-2 (p = 0.0005),
  with a decisive win rate of 84.6% (69.6-96.3).
- **EuroLLM-9B** is the only close challenger and loses on dialogue. Not
  adopted. Its 4K context is also tighter than Index at 8K.
- **Qwen3 8B** is dropped: perfect probe terms, but clearly worse prose.
- **SalamandraTA-7B** is dropped: repetition and missed terms, even with the
  colon prompt.
- Hy-MT2 Q4 stays installed only as a fallback.

## Caveats

- One repeat per model; chrF std is 0.05 to 0.11, so the chrF ordering among the
  three weakest models is not reliable.
- EuroLLM and Salamandra did not receive the style block while Index did. The
  gap may overstate Index's prose advantage; the test A/B direction is still
  supported, but a style-included rerun is the remaining fair check.
- The test split has one AI judge and no human spot-check; the dev spot-check
  (14/15) does not transfer to test automatically.
- chrF and the blind judge disagreed in the paid round (chrF favored Index,
  the judge favored Haiku), so chrF alone should not pick a winner.
- The controlled `colon_translate` prompt is an adaptation, not the verbatim
  model-card template. The official EuroLLM sentence structure was verified and
  rerun as `eurollm-9b-native`; the difference is a wash (see Results).
  Salamandra's template was not independently verified.
- pt-PT bias was assessed only through the judge's notes and the owner's picks,
  not by a dedicated metric.
- Nothing here was run on Realm of the Elderlings, where Index is the default
  from `model-selection-2026-11-09.md`.

## Reproduction

```bash
docker compose -f docker-compose.dev.yml exec -T app \
  python scripts/benchmark_fase_d.py \
  --corpus data/benchmark/literary/eval_sun_eater_dev.jsonl \
  --models qwen3-8b eurollm-9b salamandrata-7b --repeats 1 \
  --endpoint http://host.docker.internal:11434 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book "Empire of Silence" \
  --resource-book-order 1 \
  --out-root data/benchmark/eval-sun-eater-dev-v3-local

# Probes and test use the same command with probes_run_sun_eater.jsonl and
# eval_sun_eater_test.jsonl, then scripts/score_probes.py for term compliance.

# Native EuroLLM prompt check (same resources, v5 output)
python scripts/benchmark_fase_d.py \
  --corpus data/benchmark/literary/eval_sun_eater_dev.jsonl \
  --models eurollm-9b-native --repeats 1 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book "Empire of Silence" \
  --resource-book-order 1 \
  --out-root data/benchmark/eval-sun-eater-dev-v5-eurollm-native

# Blind A/B and analysis
python scripts/make_pairwise_sheet.py --corpus data/benchmark/literary/eval_sun_eater_test.jsonl \
  --run-dir data/benchmark/sun-eater-test-local-index-vs-eurollm-9b \
  --model-a index-translate-9b --model-b eurollm-9b \
  --out data/benchmark/sun-eater-test-local-index-vs-eurollm-9b/judging.jsonl
python scripts/make_judge_batches.py --sheet .../judging.jsonl --out-dir .../claude-batches \
  --batch-size 14 --series "The Sun Eater"
python scripts/run_claude_judge.py --batches .../claude-batches --out .../judgments-sonnet.jsonl \
  --raw-dir .../judgments-raw --model sonnet
python scripts/analyze_pairwise.py --reference-model index-translate-9b \
  --input .../judgments-sonnet.jsonl --sheet .../judging.jsonl --key .../judging-key.json
```
