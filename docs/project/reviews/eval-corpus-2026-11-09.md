# Evaluation corpus 2026-11-09

This replaces the 30-excerpt Fase D corpus for model selection. It keeps the
old corpus and report as history, but the decision set is now larger, audited
and split into dev/test.

## Old 30 audit

Manual paragraph-level review:

- **28 keep** — source and official PT reference match in content, names and
  length ratio.
- **2 drop**:
  - `royal-assassin-00`: the source is the Chivalry/Bearns dialogue; the
    reference is a different Bearns/Rippon/Shoaks reflection paragraph.
  - `royal-assassin-03`: the source is the snowdrop description; the reference
    is the party leaving the terrace.
- **1 additional drop in the new set**: `assassins-apprentice-22-0054`, where
  the source is Fitz's warning to Verity but the reference is a Galen/Verity
  claw paragraph. It is blacklisted by signature in the builder.

The audit rows are in `data/benchmark/literary/fase-d-audit.jsonl`.

## New corpus

| Split | Excerpts | Categories | Books |
|---|---:|---|---|
| Dev | 56 | 8 per category | AA 18, RA 19, AQ 19 |
| Test | 28 | 4 per category | AA 10, RA 9, AQ 9 |
| **Total** | **84** | **12 per category** | **AA 28, RA 28, AQ 28** |

Categories: dialogue, introspection, description, action, long_syntax, irony,
terminology. Excerpt length is 27–304 words (EN).

### Alignment

- Chapter documents are paired by index; chapters with a PT/EN word ratio
  outside 0.65–1.55 are skipped.
- Paragraphs are aligned monotonically with a dynamic-programming pass scored
  by shared names/numbers, rare-token overlap, dialogue/non-dialogue match,
  length ratio and position.
- Only high/medium confidence pairs are kept. The selected set has **82 high**
  and **2 medium** pairs; the two medium pairs are terminology passages with no
  shared names and were manually checked.
- Farseer `Buck` and `Farrow` were corrected against the actual PT text:
  **Cervo** and **Vara**, not the English names. `Buckriver` → **rio Cervo**;
  `Red-Ship Raiders` → **Salteadores dos Navios Vermelhos**; `Buckkeep Town`
  alias capitalised as **Cidade de Torre do Cervo**.

The builder is `scripts/build_eval_corpus.py`; the manifest is
`data/benchmark/literary/eval_manifest.json`.

## Probes

| File | Rows | Target |
|---|---:|---|
| `probes_names_farseer.jsonl` | 25 | 2–4 characters, official PT reference |
| `probes_terms_farseer.jsonl` | 25 | 2–3 world terms, official PT reference |
| `probes_terms_banished.jsonl` | 30 | Malice + A Time of Dread, provisional glossary |
| `probes_terms_first_law.jsonl` | 20 | A Little Hatred, provisional glossary |
| `probes_names_banished.jsonl` | 30 | Malice + A Time of Dread, provisional glossary |
| `probes_names_first_law.jsonl` | 15 | A Little Hatred, provisional glossary |

Farseer probes were filtered to **100% reference coverage**: every expected
target occurs in the official PT paragraph. This caught and fixed the
Buck/Farrow errors. Gwynne and Abercrombie probes are source-only; they measure
consistency with the provisional glossary, not official truth.

`character_pool` is included in every name probe so the scorer can detect a
name swap, not just a missing name.

## Long chapters

| ID | Book | Chapter | EN words | PT words |
|---|---|---|---:|---:|
| `long-assassins-apprentice-20` | Assassin's Apprentice | Chapter 21 | 4,793 | 4,909 |
| `long-royal-assassin-06` | Royal Assassin | 6 Forged Ones | 3,481 | 3,365 |
| `long-royal-assassin-32` | Royal Assassin | 32 Execution | 3,843 | 3,652 |

These are full chapters in the 3–5k word range. They must go through the queue
chunker, not a single 8K prompt. `scripts/run_long_context.py` uses the
production `TokenChunker` at 450 tokens and the benchmark prompt adapters.
Dry run: **16 / 12 / 13 chunks**, 6,062 / 4,349 / 4,850 source tokens. The real
run waits for the GPU to be idle.

## Scoring tools

- `scripts/score_probes.py` — per-occurrence term compliance, missing terms,
  name swaps and optional chrF. It accepts a run directory or a predictions
  JSONL.
- `scripts/score_comet.py` — reference-based COMET (`Unbabel/wmt22-comet-da`)
  for rows with `reference_pt`. COMET is not installed in the current
  environment; `requirements-comet.txt` contains the optional dependency.
  It can run on CPU after generation.
- `scripts/run_long_context.py` — production `TokenChunker` plus prompt
  adapters for the three long chapters. It records chrF, term compliance,
  chunk count and errors. Must run in the app container (tiktoken).
- `scripts/make_pairwise_sheet.py` — builds a blind A/B sheet from two model
  runs and stores the answer key separately.
- `scripts/analyze_pairwise.py` — win rate, mean score difference, paired
  bootstrap 95% CI and exact sign test from the filled sheet.
- `scripts/benchmark_fase_d.py` remains the runner for short excerpts. Use the
  new dev/test files with `--corpus`.

## Commands

```bash
# Rebuild the corpus, probes and long chapters (CPU only)
python scripts/build_eval_corpus.py

# Run Q4 vs Index on dev (GPU; wait for the queue to be idle)
python scripts/benchmark_fase_d.py \
  --corpus data/benchmark/literary/eval_farseer_dev.jsonl \
  --models hy-mt2-7b index-translate-9b --repeats 3 \
  --out-root data/benchmark/eval-dev

# Score the term/name probes
python scripts/score_probes.py \
  --probes data/benchmark/literary/probes_*_farseer.jsonl \
  --run-dir data/benchmark/eval-dev --model index-translate-9b \
  --out data/benchmark/eval-dev/probes-index.json

# COMET, after installing the optional environment
python scripts/score_comet.py \
  --corpus data/benchmark/literary/eval_farseer_dev.jsonl \
  --run-dir data/benchmark/eval-dev --model index-translate-9b \
  --out data/benchmark/eval-dev/comet-index.json

# Long chapters, dry run (no GPU)
docker compose -f docker-compose.dev.yml exec -T app python \
  scripts/run_long_context.py --dry-run

# Long chapters, real run (GPU idle)
docker compose -f docker-compose.dev.yml exec -T app python \
  scripts/run_long_context.py --models hy-mt2-7b index-translate-9b \
  --endpoint http://host.docker.internal:11434

# Blind A/B sheet and statistics
python scripts/make_pairwise_sheet.py \
  --corpus data/benchmark/literary/eval_farseer_dev.jsonl \
  --run-dir data/benchmark/eval-dev --model-a hy-mt2-7b \
  --model-b index-translate-9b --out data/benchmark/eval-dev/judging.jsonl
python scripts/analyze_pairwise.py --input data/benchmark/eval-dev/judging.jsonl
```

With 56 dev pairs the win-rate confidence interval is roughly ±7%; the 28
held-out test pairs confirm the direction. For a ±5% interval, use all 84
pairs after the dev decision, but report dev and test separately.

## Limitations

- Only Farseer has an official PT reference. Gwynne and Abercrombie probes
  measure glossary consistency, not fidelity to an official edition.
- Category labels are heuristic and were only spot-checked; a few mixed
  dialogue/description paragraphs may sit in the neighbouring category.
- The long chapters are not yet wired to the queue chunker; the 3–5k-word
  reference is for the chunked runner, not the current `benchmark_fase_d.py`.
- COMET has not been run; the dependency and checkpoint are not installed.
- No model generation was run in this pass, so the Fase D ranking is not yet
  superseded; it is now testable on a cleaner set.
