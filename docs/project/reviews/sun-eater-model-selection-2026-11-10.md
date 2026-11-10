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
   the corrected book-one resources. Cloud Gemini 3.8 Flash, DeepSeek V4.1
   Flash and Claude Haiku 5.5 with the same prompt. Temperature 0. The
   old-glossary v1 run was repeated twice with identical chrF at four decimals;
   the corrected v2/v3 runs used one repeat because the sampler is
   deterministic.
2. **Probes, 50 excerpts.** Per-occurrence term compliance, name compliance
   and name swaps. Term matching is whole-word with common Portuguese
   inflection suffixes; the old substring mode remains available with
   `--loose-terms`.
3. **Blind A/B.** Best cloud challenger against Index on the dev pairs.
4. **Held-out test, 28 excerpts.** Index, Gemini, Haiku and DeepSeek, plus a
   blind A/B on the same pairs.
5. **Long chapter.** Index, Q4, Haiku and Gemini through the production
   `TokenChunker`, then chrF, term compliance and latency.
6. **Cost.** Measured from the provider responses and extrapolated per million
   source words. The 120-word excerpts are an upper bound because the fixed
   prompt overhead is amortized over less text; the 18-chunk long chapter is
   the realistic book-chunk estimate.

Gemini 3.8 Flash completed the old-glossary dev run but its project hit the
monthly spending cap before the corrected run and probes. The cap was removed
on 2026-11-10, and the corrected run was repeated under the same 73-form prompt:
dev, 50 probes, 28 test excerpts and the 18-chunk long chapter, all with zero
errors. Its old 0.6988 is kept only as history.

Budget envelope for this round: Gemini **R$ 30 credit + R$ 61 monthly GCP**
(R$ 91 total), DeepSeek **US$ 1.38**, Claude **US$ 2.47**. Actual Gemini spend
was about **US$ 0.23** for dev + probes + test plus roughly **US$ 0.08** for the
long chapter. The Claude Sonnet judge used ten batches (about US$ 0.40
estimated). No production book translation is running; the queue is paused.

## Results

### Dev, 56 excerpts

| Model | chrF | Name recall | Latency | Cost / 56 | Cost / M source words |
|---|---:|---:|---:|---:|---:|
| **Gemini 3.8 Flash (corrected)** | **0.7033** | **0.9660** | 21.8 s | $0.0992 | $14.76 |
| Gemini 3.8 Flash (old glossary) | 0.6988 | 0.8971 | 26.5 s | $0.085 | $12.64 |
| DeepSeek V4.1 Flash | 0.6819 | 0.9631 | 17.9 s | $0.186 | $27.66 |
| Claude Haiku 5.5 | 0.6774 | 0.9354 | 4.9 s | $0.0385 | $5.73 |
| **Index-Translate 9B** | 0.6876 | 0.9626 | 5.7 s | local | local |
| Hy-MT2 7B Q4_K_M | 0.6670 | 0.9427 | 5.7 s | local | local |

The old-glossary Gemini row is historical only. The corrected Gemini row uses the
same 73-form prompt as every other row and is the finalist. The corrected
glossary raised Gemini's name recall from 0.8971 to 0.9660 and chrF from 0.6988
to 0.7033.

The corrected glossary raised name recall sharply on every model: Index
0.8015 → 0.9626, Q4 0.8358 → 0.9427, DeepSeek 0.8382 → 0.9631, Haiku
0.9069 → 0.9354. chrF moved only slightly (DeepSeek 0.6833 → 0.6819, Haiku
0.6720 → 0.6774, Index 0.6859 → 0.6876, Q4 0.6654 → 0.6670). This is the
expected effect: the glossary fixes names and titles, not prose quality.

With the same corrected prompt, **Gemini leads both chrF and name recall**:
+0.0157 chrF over Index and +0.0034 name recall. Among the remaining models,
Index is ahead of DeepSeek and Haiku on chrF; DeepSeek ties Index on name recall
and Haiku is behind. Index is 3.1× faster than DeepSeek and 3.8× faster than
Gemini, so latency favors the local model. Q4 remains the local fallback and is
behind Index by 0.0206 chrF and 0.0199 name recall. chrF is not the only signal:
the blind A/B below favors Gemini decisively.

### Gemini corrected run

Gemini was re-run on the same corrected prompt after the monthly cap was
removed. It is the strongest model on the reference metrics and in the blind
A/B.

| Split | Gemini chrF | Index chrF | Gemini names | Index names | Gemini cost |
|---|---:|---:|---:|---:|---:|
| Dev | **0.7033** | 0.6876 | **0.9660** | 0.9626 | $0.0992 |
| Test | **0.7095** | 0.6947 | 0.9733 | **0.9933** | $0.0448 |

`compare_cloud_runs.py` row counts: Gemini beats Index **42–14** on dev and
**19–9** on test; against Q4 it wins **50–6** and **24–4**. The paired rows
agree with the means.

Blind A/B judged by Claude Sonnet (non-contestant), key-normalized to Index:

| Split | Gemini wins | Index wins | Ties | Index decisive win rate | Mean Gemini | Mean Index | Sign test |
|---|---:|---:|---:|---:|---:|---:|---:|
| Dev | **38** | 2 | 16 | 5.0% | **3.91** | 2.82 | p < 0.0001 |
| Test | **17** | 4 | 7 | 19.0% | **3.96** | 3.07 | p = 0.0072 |

Direct Gemini vs Haiku, same judge and 56 dev pairs: Gemini **23**, Haiku **7**,
ties **26**; Gemini decisive win rate **76.7%**, p = 0.0052, mean score 3.84 vs
3.59. Gemini wins action 6–0 and irony 4–0; dialogue and terminology are mostly
ties. This is the cleanest ranking evidence: Gemini is the best cloud model,
Haiku is a close second, and both beat Index on prose.

### Probes, 50 excerpts

| Model | Term compliance | Name compliance | Name swaps | Probes with a miss |
|---|---:|---:|---:|---:|
| **Gemini 3.8 Flash** | **0.9915** | **1.0000** | 0 | 1 |
| **Index-Translate 9B** | **0.9915** | **1.0000** | 0 | 1 |
| **Claude Haiku 5.5** | **0.9915** | **1.0000** | 0 | 1 |
| DeepSeek V4.1 Flash | 0.9744 | 1.0000 | 0 | 2 |
| Hy-MT2 7B Q4_K_M | 0.9744 | 0.9851 | 1 | 3 |

Gemini, Index and Haiku tie on the probe gate. All three miss only
`Pale → Pálido` in probe 13; none produced a name swap. DeepSeek misses `Pale`
and the `Jaddian/Jaddians` pair. Q4 misses Gibson, Emesh and Pale and has one
swap.

### Earlier Haiku vs Index A/B, 56 dev pairs

This was the first cloud challenger pass, judged by the repository agent. The
Gemini A/Bs above are the final ranking evidence; this table is kept for
context and for the Haiku fallback decision.

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
- Caveat: one AI judge, not a professional human reviewer. The planned
  Claude A/B judge was not used: Haiku is a contestant, and the remaining
  Claude balance is reserved under the no-card-charge budget constraint. The
  judge is the repository agent.

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
| **Gemini 3.8 Flash** | **0.7095** | 0.9733 | $0.0448 |
| Index-Translate 9B | 0.6947 | **0.9933** | local |
| DeepSeek V4.1 Flash | 0.6863 | 0.9596 | $0.064 |
| Claude Haiku 5.5 | 0.6753 | **0.9933** | $0.017 |
| Hy-MT2 7B Q4_K_M | 0.6580 | 0.9267 | local |

Gemini has the higher test chrF (+0.0148 over Index) and near-perfect name
recall; Index and Haiku are slightly ahead on names (0.9933). The test A/B is
decisive for Gemini: 17–4–7 over Index, p = 0.0072. Q4 is last on both metrics.

### Long chapter

Chapter 73, 5,156 words, 18 chunks through the production `TokenChunker`:

| Model | chrF | Term compliance | Latency | Errors |
|---|---:|---:|---:|---:|
| **Gemini 3.8 Flash** | **0.7981** | 0.9474 (18/19) | 527.9 s | 0 |
| Index-Translate 9B | 0.7852 | **1.0000** (19/19) | 230.6 s | 0 |
| Claude Haiku 5.5 | 0.7761 | 0.9474 (18/19) | **132.8 s** | 0 |
| Hy-MT2 7B Q4_K_M | 0.6731 | 0.8421 (16/19) | 209.1 s | 0 |

Gemini has the best long-chapter chrF, ties Haiku on terms and is 4× slower
than Haiku (527.9 s vs 132.8 s for 5,156 words). Index has perfect term
compliance and is 2.3× faster than Gemini. All three are complete and
error-free. The only missed term for Gemini and Haiku is the book title
`Empire of Silence → Império do Silêncio`, which is metadata and does not occur
in the chapter prose. Q4 misses three terms, is 76 s slower than Haiku and,
more seriously, **omits the opening interrogation scene**: 25.8k characters
against 29.1k in the source and 31.6k in Index. Q4's zero errors do not capture
that content loss.

### Cost and budget

Measured Gemini rate: **$14.76 per million source words** from the 56 dev
excerpts ($0.0992), and **$0.0448** for the 28 test excerpts. The long chapter
confirms the model holds quality at book-chunk size, but the runner does not
record provider cost per chunk; use the excerpt rate as the conservative upper
bound. At $14.76/M, the remaining 1.38M Sun Eater words cost about **$20.4**:
*Demon in White* about **$4.4**, *Kingdoms of Death* **$3.1**, *Ashes of Man*
**$3.1**, *Disquiet Gods* **$4.2**, *Shadows Upon Time* **$5.6**. The R$ 91
Gemini budget (about US$ 16–17) covers roughly the next three books, not all
five.

Haiku at **$3.54–5.73/M** is the cheaper cloud fallback; the US$ 2.47 Claude
balance covers *Demon in White* ($1.05–1.70) and part of the next book.
DeepSeek's US$ 1.38 buys too little at $27.66/M. Local Index has no API cost but
takes roughly 13–18 hours of GPU time per 1.38M words at the measured excerpt
latency.

## Decision

**Primary model for The Sun Eater: Gemini 3.8 Flash.** It leads chrF on dev and
test (0.7033/0.7095), ties the probe gate, and wins the blind A/B against Index
(38–2 dev, 17–4 test) and against Haiku (23–7–26). The cost is the constraint:
the R$ 91 budget covers roughly the next three books. Use Gemini for *Demon in
White*, *Kingdoms of Death* and *Ashes of Man*; reassess before *Disquiet Gods*
and *Shadows Upon Time*.

**Cheaper cloud fallback: Claude Haiku 5.5.** It beats Index in prose and costs
about a third of Gemini per word. Use it for the last two Sun Eater books if
the Gemini budget runs out, or when latency matters (133 s vs 528 s on the long
chapter). Its long-chapter quality is close to Gemini and its A/B loss to
Gemini is 7–23 with 26 ties.

**Local fallback: Index-Translate 9B.** Free, perfect term compliance on the
long chapter, but loses the prose A/B to both cloud models. Use it for Realm of
the Elderlings and for any Sun Eater book that must run offline.

**Realm of the Elderlings stays on Index-Translate 9B.** The Farseer A/B and
long-chapter evidence still favor Index there.

**Q4 is not preferred.** It is behind Index on chrF, name recall and probe
compliance, with one name swap and an omitted long-chapter scene. Keep it
installed only as a local fallback.

**DeepSeek is dropped.** Lower probe compliance, about 4.8× the cost per word
and 3.6× the latency of Haiku, with no A/B advantage.

### Budget policy

Start with *Demon in White* on Gemini (295,868 words, about **$4.4**), review at
the gate, then *Kingdoms of Death* (**$3.1**) and *Ashes of Man* (**$3.1**).
That is about **$10.6** of the R$ 91 budget. Reassess before *Disquiet Gods*
and *Shadows Upon Time*: if the Gemini balance is tight, use Haiku for those two
(about **$3.0** total) or Index. Do not start a cloud book without a hard cap
and a review gate.

### Queue change

Set *Demon in White* to provider `gemini`, model `gemini-3.8-flash`; keep
`QUEUE_ALLOW_CLOUD=true`. The queue translates one chunk at a time and stops at
the review gate. Cloud drafts skip the Ollama refinement step, so the manual
review is the quality gate. Strip markdown heading markers from the draft
before EPUB assembly.

The previous Haiku experiment was paused at 137/1184 chunks; its checkpoint was
discarded, and the book is currently paused with local Index. To start Gemini,
set it to `pending`, change the model, then run with a hard cost cap. The
`translate.py` legacy-client fix from commit `f78235f` is already in place.

The old *Fool's Errand* review is also closed: its OPF was repaired
(EPUB2 metadata, duplicate cover, unique identifier), the TOC labels were
restored to `Capítulo I…XXIX`, and EPUBCheck is 0/0/0. It is exported to the
Kindle folder as `Robin Hobb/The Tawny Man Trilogy/01 - Fool's Errand (pt-BR).epub`.

### Caveats

- The Gemini vs Index and Gemini vs Haiku A/Bs were judged by Claude Sonnet
  (non-contestant) with tools disabled. The earlier Haiku vs Index pass used
  the repository agent. No professional human review yet.
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

# Gemini corrected run (same for probes/test)
docker compose -f docker-compose.dev.yml exec -T -e TEMPERATURE=0 app \
  python scripts/benchmark_cloud.py \
  --corpus data/benchmark/literary/eval_sun_eater_dev.jsonl \
  --models gemini-3.8-flash --concurrency 2 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book "Empire of Silence" \
  --resource-book-order 1 --out-root data/benchmark/cloud-sun-eater-dev-v3-gemini

# Probes and test use the same two commands with the probe/test corpus files.

# Blind A/B, Gemini vs Index
python scripts/make_pairwise_sheet.py \
  --corpus data/benchmark/literary/eval_sun_eater_dev.jsonl \
  --run-dir data/benchmark/sun-eater-dev-v3-gemini-combined \
  --model-a index-translate-9b --model-b gemini-3.8-flash \
  --out data/benchmark/sun-eater-dev-v3-gemini-combined/judging.jsonl
python scripts/make_judge_batches.py \
  --sheet data/benchmark/sun-eater-dev-v3-gemini-combined/judging.jsonl \
  --out-dir data/benchmark/sun-eater-dev-v3-gemini-combined/claude-batches \
  --batch-size 14 --series "The Sun Eater"
python scripts/run_claude_judge.py \
  --batches data/benchmark/sun-eater-dev-v3-gemini-combined/claude-batches \
  --out data/benchmark/sun-eater-dev-v3-gemini-combined/judgments-claude-sonnet.jsonl \
  --raw-dir data/benchmark/sun-eater-dev-v3-gemini-combined/claude-raw \
  --model sonnet
python scripts/analyze_pairwise.py \
  --input data/benchmark/sun-eater-dev-v3-gemini-combined/judgments-claude-sonnet.jsonl \
  --sheet data/benchmark/sun-eater-dev-v3-gemini-combined/judging.jsonl \
  --key data/benchmark/sun-eater-dev-v3-gemini-combined/judging-key.json \
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

# Long chapter, Gemini
docker compose -f docker-compose.dev.yml exec -T app \
  python scripts/run_long_context.py \
  --corpus data/benchmark/literary/long_chapters_sun_eater.jsonl \
  --cloud-model gemini-3.8-flash \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book-order 1
```
