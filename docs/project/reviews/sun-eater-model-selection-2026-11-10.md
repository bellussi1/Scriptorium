# Sun Eater model selection 2026-11-10

Priority series: **The Sun Eater**. Book 1, *Empire of Silence*, has an official
Brazilian edition (Calibre 436), a matching English source and enough aligned
prose to support the same reference-based evaluation used for Realm of the
Elderlings. The decision below is about the translation model for Sun Eater;
Farseer/Realm remains on the local Index default from
`model-selection-2026-11-09.md`.

## Corpus

Built by `scripts/build_sun_eater_corpus.py` from the English *Empire of
Silence* EPUB and the official PT-BR edition. Chapters are paired by chapter
number, paragraphs are aligned monotonically, and only high-confidence pairs
enter the selection.

| Split | Excerpts | Categories | Words (EN) |
|---|---:|---|---:|
| Dev | 56 | 8 per category | 14–245 |
| Test | 28 | 4 per category | 12–179 |
| **Total** | **84** | **12 per category** | |

Categories: dialogue, introspection, description, action, long_syntax, irony,
terminology. Dev and test share no ids or source text. All 84 selected pairs
are high confidence, ratio 0.71–1.28, and carry the official PT paragraph as
`reference_pt`.

Additional artifacts:

| File | Rows | Purpose |
|---|---:|---|
| `probes_names_sun_eater.jsonl` | 25 | 2–4 character names, official PT reference |
| `probes_terms_sun_eater.jsonl` | 25 | 2–6 world terms, official PT reference |
| `probes_run_sun_eater.jsonl` | 50 | combined probe file; no duplicate text |
| `long_chapters_sun_eater.jsonl` | 1 | Chapter 73, 5,156 EN words |

Probe reference coverage is at least 0.66; every expected probe term is now
present in the book-one glossary used by the prompt. The long chapter is
5,156 words / 7,062 source tokens and chunks into **18** production chunks at
450 tokens.

## Resource audit

The first Sun Eater run exposed a resource problem: the book-one compiled
glossary had only **17 terms / 31 prompt forms**. Many terms that actually occur
in *Empire of Silence* were marked `first_appearance: howling-dark` or later,
so the prompt omitted Valka, Switch, Ghen, Bassander, Siran, Gibson, Emesh,
Borosevo, Meidua, Imperium, Quiet, Pale and others.

`scripts/audit_sun_eater_resources.py` counts every source form in the English
book and every target form in the official Portuguese book. It promoted **30
verified terms** to `empire-of-silence` and corrected five targets that did not
match the official edition:

| Source | Old target | Official PT | Evidence |
|---|---|---|---|
| Gibson of Syracuse | Gibson of Syracuse | **Gibson de Siracusa** | 1 occurrence in book 1 |
| Siran of Emesh | Siran of Emesh | **Siran** | official edition uses the short form; the full epithet does not occur |
| Pale | Pale | **Pálido** | "os Pálidos" |
| Quiet | Quiet | **Quieto** | "os Quietos" |
| Forum | Forum | **Fórum** | accented in the official edition |

The compiled book-one glossary is now **47 terms / 73 prompt forms**. The audit
keeps `Watchers` provisional: its Portuguese hits are the ordinary adjective
"vigilantes", not the later-book entity. `resources validate` passes with 39
files and zero issues.

The benchmark prompt also had an independent bug: it mapped every alias to the
main target, so the model was told `Hadrian -> Hadrian Marlowe` and
`Gibson -> Gibson de Siracusa` even when the source used the short form. The
runner now uses the same alias-target groups as the production prompt path.

## Method

1. **Dev, 56 excerpts.** Local Index-Translate 9B and Hy-MT2 7B Q4_K_M with
   the corrected book-one resources. Cloud DeepSeek V4.1 Flash and Claude
   Haiku 5.5 with the same prompt. Temperature 0.
2. **Probes, 50 excerpts.** Per-occurrence term compliance, name compliance
   and name swaps. Term matching is whole-word with common Portuguese
   inflection suffixes; the old substring mode remains available with
   `--loose-terms`.
3. **Blind A/B.** Best cloud challenger against Index on the dev pairs.
4. **Held-out test, 28 excerpts.** Index, Haiku and DeepSeek, plus a blind A/B
   on the same pairs.
5. **Long chapter.** Index, Q4 and Haiku through the production `TokenChunker`,
   then chrF, term compliance and latency.
6. **Cost.** Measured from the provider responses and extrapolated per million
   source words. The 120-word excerpts are an upper bound because the fixed
   prompt overhead is amortized over less text; the 18-chunk long chapter is
   the realistic book-chunk estimate.

Gemini 3.8 Flash completed the old-glossary dev run but its project hit the
monthly spending cap before the corrected run and probes. It is therefore not a
finalist; its old-glossary number is reported only as historical context.

## Results

### Dev, 56 excerpts

| Model | chrF | Name recall | Latency | Cost / 56 | Cost / M source words |
|---|---:|---:|---:|---:|---:|
| Gemini 3.8 Flash (old glossary) | 0.6988 | 0.8971 | 26.5 s | $0.085 | $12.64 |
| DeepSeek V4.1 Flash | 0.6819 | 0.9631 | 17.9 s | $0.186 | $27.66 |
| Claude Haiku 5.5 | 0.6774 | 0.9354 | 4.9 s | $0.0385 | $5.73 |
| **Index-Translate 9B** | **0.6876** | **0.9626** | 5.7 s | local | local |
| Hy-MT2 7B Q4_K_M | 0.6670 | 0.9427 | 5.7 s | local | local |

The Gemini row used the old 31-form prompt and cannot be compared directly
with the corrected 73-form rows. The project hit its monthly spending cap
before the corrected run and probes; Gemini is not a finalist.

The corrected glossary raised name recall sharply on every model: Index
0.8015 → 0.9626, Q4 0.8358 → 0.9427, DeepSeek 0.8382 → 0.9631, Haiku
0.9069 → 0.9354. chrF moved only slightly (DeepSeek 0.6833 → 0.6819, Haiku
0.6720 → 0.6774, Index 0.6859 → 0.6876, Q4 0.6654 → 0.6670). This is the
expected effect: the glossary fixes names and titles, not prose quality.

With the same corrected prompt, **Index is ahead of both available cloud
models on chrF**: +0.0057 over DeepSeek and +0.0102 over Haiku. Name recall is
statistically tied with DeepSeek (0.9626 vs 0.9631) and +0.027 over Haiku.
Index is also 3.1× faster than DeepSeek. Q4 remains the local fallback and is
behind Index by 0.0206 chrF and 0.0199 name recall. chrF is not the only
signal: the blind A/B below favors Haiku despite Index's chrF lead.

### Probes, 50 excerpts

| Model | Term compliance | Name compliance | Name swaps | Probes with a miss |
|---|---:|---:|---:|---:|
| **Index-Translate 9B** | **0.9915** | **1.0000** | 0 | 1 |
| **Claude Haiku 5.5** | **0.9915** | **1.0000** | 0 | 1 |
| DeepSeek V4.1 Flash | 0.9744 | 1.0000 | 0 | 2 |
| Hy-MT2 7B Q4_K_M | 0.9744 | 0.9851 | 1 | 3 |

Index and Haiku tie on the probe gate. Both miss only `Pale → Pálido` in
probe 13; neither produced a name swap. DeepSeek misses `Pale` and the
`Jaddian/Jaddians` pair. Q4 misses Gibson, Emesh and Pale and has one swap.

### Blind A/B, 56 dev pairs

One blind judge (the repository agent), key-normalized to Index:

| Index wins | Haiku wins | Ties | Index decisive win rate | Mean Index | Mean Haiku | Sign test |
|---:|---:|---:|---:|---:|---:|---:|
| 12 | **37** | 7 | 24.5% | 3.268 | **3.768** | p = 0.0005 |

- Row bootstrap 95% CI for the Index win rate: **13.0%–36.7%**; mean score
  difference **−0.500** (CI −0.714 to −0.286).
- Haiku wins every category: action 7–0, dialogue 6–1, irony 6–2, long syntax
  5–3, description 5–2, introspection 4–3, terminology 4–1 with 3 ties.
- This is the opposite of chrF. chrF rewards closeness to the published
  reference; the blind judge rewarded natural Brazilian Portuguese, dialogue
  register and the absence of pt-PT forms and calques. The qualitative review
  agrees: Index repeatedly slips into `tu/despertaste`, `quilómetros`,
  `fazer-vos`, `se tinha deslocado`, and gender errors such as `o inquisidor`
  for a female inquisitor. Haiku makes fewer of these errors.
- Caveat: one AI judge, not a professional human reviewer. A Claude-family
  judge was deliberately not used because Haiku is a contestant.

Held-out A/B on the 28 test pairs, same judge and key normalization:

| Index wins | Haiku wins | Ties | Index decisive win rate | Mean Index | Mean Haiku | Sign test |
|---:|---:|---:|---:|---:|---:|---:|
| 7 | **16** | 5 | 30.4% | 3.393 | **3.750** | p = 0.0931 |

The test direction matches dev, but the effect is smaller and does not reach
significance at 28 items. The bootstrap 95% CI for the Index win rate is
12.5%–50.0%. Combined over 84 pairs, Index wins 19, Haiku wins 53, with 12
ties: Index decisive win rate **26.4%**, sign test **p = 0.000076**. The
dev result is the strong signal; the test is directionally consistent but not
decisive on its own.

### Held-out test, 28 excerpts

| Model | chrF | Name recall | Cost |
|---|---:|---:|---:|
| **Index-Translate 9B** | **0.6947** | **0.9933** | local |
| DeepSeek V4.1 Flash | 0.6863 | 0.9596 | $0.064 |
| Claude Haiku 5.5 | 0.6753 | **0.9933** | $0.017 |
| Hy-MT2 7B Q4_K_M | 0.6580 | 0.9267 | local |

The test set repeats the dev pattern: Index has the higher chrF (+0.0194 over
Haiku) and ties Haiku on name recall, while Haiku costs $0.017 and DeepSeek is
more expensive with lower name recall. Q4 is last on both metrics. The test
chrF gap is why the held-out A/B matters; it is reported above.

### Long chapter

Chapter 73, 5,156 words, 18 chunks through the production `TokenChunker`:

| Model | chrF | Term compliance | Latency | Errors |
|---|---:|---:|---:|---:|
| **Index-Translate 9B** | **0.7852** | **1.0000** (19/19) | 230.6 s | 0 |
| Claude Haiku 5.5 | 0.7761 | 0.9474 (18/19) | **132.8 s** | 0 |
| Hy-MT2 7B Q4_K_M | 0.6731 | 0.8421 (16/19) | 209.1 s | 0 |

Index has the best long-chapter chrF and perfect term compliance; Haiku is
1.7× faster and misses only the book title `Empire of Silence → Império do
Silêncio`, which is metadata and does not occur in the chapter prose. Both keep
the chapter complete. Q4 misses three terms, is 76 s slower than Haiku and,
more seriously, **omits the opening interrogation scene**: 25.8k characters
against 29.1k in the source and 31.6k in Index. Q4's zero errors do not capture
that content loss.

### Cost and budget

At the measured Haiku rate the remaining 1.38M Sun Eater words cost
**$4.9–7.9**: **$3.54/M** from the 18-chunk long chapter (the realistic
book-chunk shape) and **$5.73/M** from 120-word excerpts (an upper bound
because the prompt overhead is amortized over less text). The full 7.5M-word
queue costs about **$26–43**. The next queue book, *Demon in White*, is
295,868 words and costs about **$1.05–1.70**. The available Claude credit
therefore covers roughly two to three Sun Eater volumes, not the whole series.
DeepSeek is about 4.8× more expensive per word and 3.6× slower, with lower
probe compliance. Local Index has no API cost but takes roughly 13–18 hours of
GPU time per 1.38M words at the measured excerpt latency.

## Decision

**Primary model for The Sun Eater: Claude Haiku 5.5, through LiteLLM.** The
dev blind A/B is decisive (37–12, p = 0.0005); the held-out test A/B points the
same way (16–7–5, p = 0.093) and the combined 84-pair result is 53–19–12 for
Haiku (p = 0.000076). The probe gate is tied with Index. On the long chapter,
Index is slightly ahead on chrF and term compliance (0.7852/1.0 vs
0.7761/0.9474) but is 1.7× slower; both are complete and error-free. Haiku's
advantage is prose naturalness and pt-BR register; Index's is reference
similarity, terminology and zero API cost. This is a judgment call, not a clean
sweep: Index is the safer, free option, and Haiku is the better reading
experience. Index remains the fallback.

**Realm of the Elderlings stays on Index-Translate 9B.** The Farseer A/B and
long-chapter evidence still favor Index there.

**Q4 is not preferred.** It is behind Index on chrF, name recall and probe
compliance, with one name swap. Keep it installed only as a local fallback.

**Gemini is not a finalist.** The project hit its monthly spending cap before
the corrected run and probes. If the cap is raised, rerun dev and probes with
the 73-form prompt before comparing it; the old 0.6988 is not comparable.

**DeepSeek is dropped.** Lower probe compliance, about 4.8× the cost per word
and 3.6× the latency of Haiku, with no A/B advantage.

### Budget policy

Start with *Demon in White* on Haiku (295,868 words, about **$1.05–1.70**),
review at the gate, and continue while credit remains. The remaining Claude
credit covers roughly two to three Sun Eater volumes. If the gate finds
systematic errors or the credit runs out, fall back to Index for the rest of
Sun Eater. Do not translate the whole series in the cloud without a new budget
decision.

### Queue change

Set *Demon in White* to provider `litellm`, model
`anthropic/claude-haiku-5-5`; keep `QUEUE_ALLOW_CLOUD=true`. The queue
translates one chunk at a time and stops at the review gate. Cloud drafts skip
the Ollama refinement step, so the manual review is the quality gate. Strip
markdown heading markers from the draft before EPUB assembly; Haiku added two
`#` headings in the long chapter.

### Caveats

- One blind AI judge, not a professional human reviewer. The judge is the
  repository agent; a Claude-family judge was not used because Haiku is a
  contestant.
- The A/B used the benchmark prompt, not the full production prompt; the queue
  review gate remains mandatory.
- The long chapter is one chapter from one book. The held-out test and the
  first queue book are the next gates.

## Reproduction

```bash
# Corpus, probes, long chapter (CPU)
python scripts/build_sun_eater_corpus.py

# Resource audit (CPU; --apply edits the YAML)
python scripts/audit_sun_eater_resources.py

# Dev, local
python scripts/benchmark_fase_d.py \
  --corpus data/benchmark/literary/eval_sun_eater_dev.jsonl \
  --models hy-mt2-7b index-translate-9b --repeats 1 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book "Empire of Silence" \
  --resource-book-order 1 --out-root data/benchmark/eval-sun-eater-dev-v2

# Dev, cloud
docker compose -f docker-compose.dev.yml exec -T -e TEMPERATURE=0 app \
  python scripts/benchmark_cloud.py \
  --corpus data/benchmark/literary/eval_sun_eater_dev.jsonl \
  --models deepseek-flash claude-haiku-5-5 --concurrency 4 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book "Empire of Silence" \
  --resource-book-order 1 --out-root data/benchmark/cloud-sun-eater-dev-v2

# Probes and test use the same two commands with the probe/test corpus files.

# Blind A/B
python scripts/make_pairwise_sheet.py \
  --corpus data/benchmark/literary/eval_sun_eater_dev.jsonl \
  --run-dir data/benchmark/sun-eater-dev-v2-combined \
  --model-a index-translate-9b --model-b claude-haiku-5-5 \
  --out data/benchmark/sun-eater-dev-v2-combined/judging.jsonl
python scripts/make_judge_batches.py \
  --sheet data/benchmark/sun-eater-dev-v2-combined/judging.jsonl \
  --out-dir data/benchmark/sun-eater-dev-v2-combined/claude-batches \
  --batch-size 14 --series "The Sun Eater"
python scripts/analyze_pairwise.py \
  --input data/benchmark/sun-eater-dev-v2-combined/judgments-agent.jsonl \
  --sheet data/benchmark/sun-eater-dev-v2-combined/judging.jsonl \
  --key data/benchmark/sun-eater-dev-v2-combined/judging-key.json \
  --reference-model index-translate-9b

# Long chapter, local
docker compose -f docker-compose.dev.yml exec -T app \
  python scripts/run_long_context.py \
  --corpus data/benchmark/literary/long_chapters_sun_eater.jsonl \
  --models hy-mt2-7b index-translate-9b \
  --endpoint http://host.docker.internal:11434 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book-order 1

# Long chapter, cloud
docker compose -f docker-compose.dev.yml exec -T app \
  python scripts/run_long_context.py \
  --corpus data/benchmark/literary/long_chapters_sun_eater.jsonl \
  --cloud-model claude-haiku-5-5 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book-order 1
```
