# Local model benchmark: EuroLLM, Salamandra, Qwen3 vs Index (2026-11-10)

Question: does any local model beat Index-Translate 9B for English to Brazilian
Portuguese literary translation on the 8 GB card? Companion to
`sun-eater-model-selection-2026-11-10.md`, which covers the paid models.

## Setup

- Corpus: Sun Eater, *Empire of Silence*, dev 56 / probes 50 / test 28, official
  PT-BR reference. Same 73-form glossary and style prompt as the paid round.
- Models run here, one repeat each, Ollama on the host, Q4_K_M:
  Qwen3 8B, EuroLLM-9B (community GGUF), SalamandraTA-7B (BSC-LT GGUF).
  Index-Translate 9B and Hy-MT2 Q4 are reused from the earlier v2 runs on the
  same corpus and prompt.
- Output: `data/benchmark/eval-sun-eater-{dev,probes,test}-v3-local/`.
- Code: `benchmark/literary/adapters.py` registers `eurollm-9b` and
  `salamandrata-7b` with a new `colon_translate` prompt style
  (`Translate ... from English into Brazilian Portuguese.\nEnglish: ...\nPortuguese:`).
  The format is from memory of the model cards and is **not verified**. The
  generic system prompt made Salamandra translate the instructions instead of
  the text (chrF 0.34 on a 3-excerpt smoke test), so it is not a fair prompt
  for either model.

## Results

| Model | Dev chrF | Test chrF | Dev names | Probe terms | Dev repetition |
|---|---:|---:|---:|---:|---:|
| Index 9B | **0.6876** | **0.6947** | 0.9626 | 0.9915 | n/a |
| EuroLLM-9B | 0.6785 | 0.6804 | 0.9461 | 0.9829 | 0.014 |
| Hy-MT2 Q4 | 0.6670 | 0.6580 | 0.9427 | 0.9744 | n/a |
| Qwen3 8B | 0.6495 | 0.6581 | 0.9495 | **1.0** | 0.014 |
| SalamandraTA-7B | 0.6559 | 0.6796 | 0.9009 | 0.906 | 0.119 |

Latency is 4 to 5 s p50 per excerpt for all of them, with the GPU free.
Salamandra has a length ratio of 1.13 on dev and misses 8 probes, so it was
not judged.

## Blind A/B, dev (56 pairs, key-normalized to Index)

| Pair | Index | Other | Ties | Sign test | Index decisive win rate (95% CI) |
|---|---:|---:|---:|---:|---|
| Index vs EuroLLM | 36 | 19 | 1 | p = 0.03 | 65.5% (52.7-78.2) |
| Index vs Qwen3 | 42 | 11 | 3 | p < 0.0001 | 79.3% (67.9-89.3) |

Index leads EuroLLM in every category except action (3-5). The gap is widest in
dialogue (7-1) and terminology (6-2).

Judges: one subagent per pair, reading only the anonymized batches and never
the key. Same kind of single AI judge as the earlier A/B rounds, not a
professional reviewer.

Human check: 15 blind Index-vs-EuroLLM pairs, 2 per category (3 description).
The owner agreed with the judge on **14 of 15**; the owner picked Index 9 times
and EuroLLM 6 times, the judge Index 10 times. Fifteen pairs calibrate the
judge but do not prove the 56-pair result by themselves.

## Decision

- **Local default stays Index-Translate 9B**, for Sun Eater fallback and for
  Realm of the Elderlings.
- **EuroLLM-9B** is the only close challenger and loses on dialogue. Not
  adopted. Its 4K context is also tighter than Index at 8K.
- **Qwen3 8B** is dropped: perfect probe terms, but clearly worse prose.
- **SalamandraTA-7B** is dropped: repetition and missed terms, even with the
  colon prompt.
- Hy-MT2 Q4 stays installed only as a fallback.

## Caveats

- One repeat per model; chrF std is 0.05 to 0.11, so the chrF ordering among the
  three weakest models is not reliable.
- Dev only for the A/B. The 28-pair test split was not judged.
- chrF and the blind judge disagreed in the paid round (chrF favored Index,
  the judge favored Haiku), so chrF alone should not pick a winner.
- The `colon_translate` prompts are unverified against the model cards; a
  verified native prompt could change EuroLLM and Salamandra results.
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

# Blind A/B and analysis
python scripts/make_pairwise_sheet.py --corpus data/benchmark/literary/eval_sun_eater_dev.jsonl \
  --run-dir data/benchmark/sun-eater-dev-local-index-vs-eurollm-9b \
  --model-a index-translate-9b --model-b eurollm-9b \
  --out data/benchmark/sun-eater-dev-local-index-vs-eurollm-9b/judging.jsonl --seed 7
python scripts/analyze_pairwise.py --reference-model index-translate-9b \
  --input .../judgments-agent.jsonl --sheet .../judging.jsonl --key .../judging-key.json
```
