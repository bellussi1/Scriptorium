---
name: Model Benchmark
description: Run and interpret the English-to-Brazilian-Portuguese literary model benchmark in this repository. Use when comparing local Ollama models or cloud models, adding a new candidate, running the Sun Eater corpus and probes, or deciding which model to use for a series.
---

# Model Benchmark

The benchmark answers one question: which model gives the best reading
experience for this English-to-Brazilian-Portuguese literary project, within a
known budget. chrF alone is not the answer.

## Evaluation set

- **Dev:** 56 excerpts, 8 per category: dialogue, introspection, description,
  action, long_syntax, irony, terminology.
- **Test:** 28 held-out excerpts, 4 per category. No id or source text overlaps
  dev or probes.
- **Probes:** 25 name + 25 term excerpts, official PT reference, no duplicate
  text. Score term compliance, name compliance and name swaps.
- **Long chapter:** one 3–5.5k-word chapter through the production
  `TokenChunker` (450 tokens), 18 chunks for Sun Eater chapter 73.
- **Reference:** official PT-BR editions. For Sun Eater, *Empire of Silence*,
  Calibre 436.

Build the Sun Eater artifacts with:

```bash
python scripts/build_sun_eater_corpus.py
python scripts/audit_sun_eater_resources.py
```

The builder emits `eval_sun_eater_dev.jsonl`, `eval_sun_eater_test.jsonl`,
`probes_*_sun_eater.jsonl`, `probes_run_sun_eater.jsonl` and
`long_chapters_sun_eater.jsonl` under `data/benchmark/literary/`.

## Local run

```bash
python scripts/benchmark_fase_d.py --corpus <corpus.jsonl> \
  --models hy-mt2-7b index-translate-9b --repeats 1 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book "Empire of Silence" \
  --resource-book-order 1 --out-root <out>
```

Temperature 0 is deterministic; one repeat is enough after confirming two
repeats match at four decimals. Do not run this while the queue is translating.

## Cloud run

```bash
docker compose -f docker-compose.dev.yml exec -T -e TEMPERATURE=0 app \
  python scripts/benchmark_cloud.py --corpus <corpus.jsonl> \
  --models gemini-3.8-flash claude-haiku-5-5 --concurrency 2 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book "Empire of Silence" \
  --resource-book-order 1 --out-root <out>
```

Use `--concurrency 2` for Gemini to avoid rate limits. The benchmark uses the
same controlled literary prompt and the same 73-form glossary/style for every
model; do not compare a provider's native chat template against this prompt.

## Scoring

```bash
python scripts/score_probes.py --probes <probes.jsonl> --run-dir <run> --model <model>
python scripts/compare_cloud_runs.py --cloud-run <cloud> --local-run <local>
python scripts/run_long_context.py --corpus <long.jsonl> \
  --cloud-model gemini-3.8-flash \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book-order 1
```

- chrF: reference similarity; report dev, test and long chapter separately.
- Name recall: fraction of expected names present.
- Probe term compliance: whole-word matching with common Portuguese inflections.
- Long chapter: chrF, term compliance, latency, errors **and output length**.
  A model that omits a scene can still score zero errors.

## Blind A/B

Build a sheet from two model runs and keep the key separate:

```bash
python scripts/make_pairwise_sheet.py --corpus <dev.jsonl> --run-dir <combined> \
  --model-a index-translate-9b --model-b gemini-3.8-flash --out <sheet>
python scripts/make_judge_batches.py --sheet <sheet> --out-dir <batches> \
  --batch-size 14 --series "The Sun Eater"
```

Use a **non-contestant** judge. Claude Sonnet is acceptable for Gemini/Haiku
comparisons; do not use a contestant as the only judge. Run:

```bash
python scripts/run_claude_judge.py --batches <batches> --out <judgments> \
  --raw-dir <raw> --model sonnet
python scripts/analyze_pairwise.py --input <judgments> --sheet <sheet> \
  --key <key> --reference-model index-translate-9b
```

The analyzer normalizes per-row A/B swaps and reports a paired bootstrap CI, a
book-cluster bootstrap and an exact sign test. Read the per-category table, not
only the overall win rate.

## Decision criteria

1. **Gate first:** any model with name swaps, English leakage or broken output
   is out, regardless of chrF.
2. **Probe gate:** term/name compliance at or above the incumbent. A tie is
   fine; a regression is not.
3. **Blind A/B:** the primary prose signal. A 60/40 split is weak; a 70/30 split
   with a sign test below 0.05 is meaningful.
4. **chrF and test set:** reference similarity and held-out stability. Do not
   choose a model on dev alone.
5. **Long chapter:** completeness and term consistency. Compare output length
   and the first/last paragraphs.
6. **Cost and latency:** cost per million source words and wall-clock time. A
   model that wins prose but costs 5× more needs a budget case.

## Current evidence (2026-11-10)

Sun Eater, *Empire of Silence*:

| Model | Dev chrF | Test chrF | Dev names | Test names | Probe terms | Long chrF |
|---|---:|---:|---:|---:|---:|---:|
| Gemini 3.8 Flash | **0.7033** | **0.7095** | 0.9660 | 0.9733 | 0.9915 | **0.7981** |
| Index 9B | 0.6876 | 0.6947 | 0.9626 | **0.9933** | 0.9915 | 0.7852 |
| DeepSeek V4.1 | 0.6819 | 0.6863 | 0.9631 | 0.9596 | 0.9744 | not run |
| Haiku 5.5 | 0.6774 | 0.6753 | 0.9354 | 0.9933 | 0.9915 | 0.7761 |
| Hy-MT2 Q4 | 0.6670 | 0.6580 | 0.9427 | 0.9267 | 0.9744 | 0.6731 |

Blind A/B, Claude Sonnet: Gemini beats Index 38–2 dev and 17–4 test; Gemini
beats Haiku 23–7 with 26 ties. Decision: Gemini primary for Sun Eater, Haiku
cheaper cloud fallback, Index free local fallback, Realm of the Elderlings on
Index.

## Pitfalls

- Comparing models with different glossaries. Rebuild the prompt resources and
  verify every probe term is in the book-one glossary.
- Using the old 31-form Sun Eater prompt. The corrected prompt has 47 terms /
  73 forms.
- Forgetting that temperature 0 makes repeats identical; do not waste GPU time
  on three repeats without checking.
- Mixing a partial checkpoint from one provider with a new provider. Clear the
  resume state first.
- Treating a TOC/label bug as a translation bug. Validate metadata separately.
- Reporting a cloud cost from an old balance. Query DeepSeek or check the
  provider console; keep `data/cost_ledger.jsonl` current.
