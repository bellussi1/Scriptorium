# Local model selection — English to Brazilian Portuguese

Date: 2026-11-09. Hardware: single 8 GB NVIDIA GPU, Ollama, one request at a
time. Use: the owner's personal literary reading only; model licenses are
recorded for transparency but are not a distribution gate.

## Question

Which local model should the literary queue use for English-to-Brazilian-
Portuguese book translation on this machine?

The answer is deliberately narrow: the best measured model on this corpus and
hardware, not a claim about an absolute best translation system.

## Candidates

| Model | Params | Quant | License | Status |
|---|---:|---|---|---|
| Index-Translate 9B | 9B | Q4_K_M | Apache-2.0 | incumbent |
| Hy-MT2 7B | 7B | Q4_K_M | Apache-2.0 | incumbent fallback |
| SalamandraTA-7B-instruct v3 | 7B | Q4_K_M | GPL-3.0 | rejected at smoke |
| EuroLLM-9B-Instruct | 9B | Q4_K_M | Apache-2.0 | rejected at smoke |
| Seed-X-PPO-7B | 7B | Q4_K_M (third-party) | OpenMDW | reserve, not tested |

The owner confirmed that the use is personal reading only, so the GPL-3.0
SalamandraTA license was not treated as a blocker. Licenses are recorded for
transparency; they did not decide the ranking.

The base Salamandra-7B-Instruct is Apache-2.0, but it is not the
translation-tuned model. The translation variant, SalamandraTA, is GPL-3.0.
Seed-X has no official GGUF, has no chat template and expects a trailing
`<pt>` tag and beam search in its reference setup.

## Method

- **Dev:** 56 Farseer excerpts, 8 per category (dialogue, introspection,
  description, action, long_syntax, irony, terminology), 3 repeats per model.
- **Test:** 28 held-out Farseer excerpts, 3 repeats, not used for any decision
  before the dev choice.
- **Probes:** 145 name/term probes. Farseer targets come from the official
  PT-BR edition; Gwynne and Abercrombie targets come from the provisional
  shared-world glossaries and measure consistency, not official truth.
- **Long chapters:** three 3–5k-word chapters through the production chunker.
- **Blind A/B:** 56 dev pairs, randomized A/B order, per-row answer key. Two
  judges: the repository agent and a Claude model. Scores were normalized to a
  fixed model before computing wins.
- **COMET:** `Unbabel/wmt22-comet-da`, reference-based, CPU.
- **Decision rule:** hard gates first (no errors, no truncation, placeholder
  integrity, no English leakage, no invented facts), then blind preference and
  terminology, then chrF/COMET and latency. Ties go to the incumbent.

## Dev results

3 repeats × 56 excerpts = 168 generations per model. Zero errors.

| Metric | Index 9B | Hy-MT2 7B Q4 |
|---|---:|---:|
| chrF mean | **0.7192** | 0.6762 |
| chrF std | 0.0596 | 0.0583 |
| Latency mean | 5.80 s | 5.74 s |
| Latency p95 | 10.94 s | 10.12 s |
| Output tokens | 195.2 | 217.2 |
| Length ratio | 1.0249 | 0.9687 |
| Name recall | 0.9702 | 0.9799 |
| English leakage | 0.0004 | 0.0006 |
| Repetition | 0.0109 | 0.0115 |

Paired by excerpt: Index wins **47 of 56**, mean chrF delta **+0.0431**
(median +0.0472). Index is ahead in all seven categories; the largest gaps are
long syntax (+0.0798), irony (+0.0662) and terminology (+0.0565), the smallest
is action (+0.0052).

Latency is effectively equal on short excerpts. The long chapters show the
real cost, below.

## Long chapters

Three full chapters through the production chunker:

| Chapter | Index chrF | Q4 chrF | Index terms | Q4 terms | Index latency | Q4 latency |
|---|---:|---:|---:|---:|---:|---:|
| Assassin's Apprentice 21 | **0.7997** | 0.7298 | **1.0000** | 0.9333 | 214.2 s | 192.8 s |
| Royal Assassin 6 | **0.8028** | 0.6765 | **0.9615** | 0.7308 | 146.2 s | 129.8 s |
| Royal Assassin 32 | **0.8110** | 0.7370 | 0.8125 | 0.8125 | 171.7 s | 154.4 s |
| Mean | **0.8045** | 0.7144 | **0.9247** | 0.8255 | 177.3 s | 159.0 s |

Zero errors in both. Index costs about **11.5% more latency** on full chapters
and is clearly ahead on chrF and terminology. This is the strongest evidence
that the short-excerpt tie in latency does not survive book-scale generation.

## Blind A/B

Normalized to Index as the reference model.

| Judge | Index wins | Q4 wins | Ties | Decisive win rate | Mean score Index | Mean score Q4 | Sign test |
|---|---:|---:|---:|---:|---:|---:|---:|
| Repository agent | 35 | 13 | 8 | 72.9% | 3.625 | 3.054 | p = 0.0021 |
| Claude (Opus 5.5, tools disabled) | 29 | 14 | 13 | 67.4% | 3.607 | 3.000 | p = 0.0315 |

- Agent bootstrap 95% CI for the win rate: 60.0%–85.1%; mean score difference
  +0.571 (CI 0.268–0.875).
- Claude bootstrap 95% CI for the win rate: 53.5%–80.9%; mean score difference
  +0.607 (CI 0.304–0.929).
- Book-clustered CIs remain above zero for both judges.
- Item agreement is moderate: 31/56 (55.4%), Cohen's kappa 0.237. Both judges
  agree on 23 Index wins and 6 Q4 wins; 8 rows are opposite and the remaining
  17 are ties on one side. The disagreement is mostly "slight win vs tie", not
  a reversal of the ranking.
- Per category, the agent put Index ahead in all seven; Claude put Index ahead
  in action, description, long syntax and terminology, split dialogue, and
  favored Q4 on irony (5–2). Irony is the one genre where the choice is not
  settled.

The A/B result is the primary quality signal. The Claude judge was blind:
it received only the randomized sheet, with tools disabled and no access to
the answer key. The repository agent also scored the anonymous sheet, but it
had seen some model outputs during the benchmark run before judging; its
result is therefore secondary to the Claude pass. The key was applied only
after both passes were complete.

## COMET

`wmt22-comet-da` on the 56 dev excerpts:

| Model | System score | Wins |
|---|---:|---:|
| Index 9B | **0.8179** | 36 |
| Hy-MT2 7B Q4 | 0.8123 | 20 |

Mean paired difference: **+0.00565** (95% bootstrap CI −0.00074 to +0.01219).
The CI includes zero. COMET therefore does **not** establish a reliable Index
advantage; it says the two outputs are semantically close. The blind A/B and
chrF/terminology results carry the decision.

By category, Index is ahead on description (+0.0102), dialogue (+0.0098),
terminology (+0.0221), irony (+0.0088) and action (+0.0035); Q4 is ahead on
introspection (−0.0142) and effectively tied on long syntax (−0.0008). This is
consistent with the idea that Index's edge is strongest on names, terms and
surface fidelity, not on every dimension of prose.

On the held-out test set, COMET gives Index 0.8147 and Q4 0.8089, a mean paired
difference of +0.00582 (95% CI −0.00432 to +0.01668; Index wins 15 of 28).
The semantic gap is again small and not statistically robust.

## Probes

Corrected 145-probe run, one repeat. Both models produced 145 predictions and
zero errors.

| Slice | Index term | Q4 term | Index name | Q4 name | Index swaps | Q4 swaps |
|---|---:|---:|---:|---:|---:|---:|
| All probes | **0.7579** | 0.7158 | **0.7946** | 0.7825 | **13** | 15 |
| Farseer (official PT) | **0.9470** | 0.9318 | **1.0000** | 0.9922 | 0 | 0 |
| Banished Lands (provisional) | **0.6139** | 0.5676 | 0.5467 | 0.5467 | **13** | 15 |
| First Law (provisional) | **0.9048** | 0.8333 | **1.0000** | 0.9423 | 0 | 0 |

Index is ahead on every slice except Banished Lands names, where the two are
tied at 54.67%. The Farseer slice is the only one with official-reference
truth; the other two measure consistency with the provisional shared-world
glossaries. Both models struggle with the Banished name pool, so that tie is
not evidence that Q4 is equally good at names in general.

The scorer treats a short form such as "Shrewd" as the same entity as
"Rei Shrewd"; the 13 and 15 swaps are genuine different-character
substitutions. Index has at least one missing expected item in 52 probes; Q4
has 63.

## Test set

Held out until after the dev decision. 28 excerpts, 3 repeats, zero errors.

| Metric | Index 9B | Hy-MT2 7B Q4 |
|---|---:|---:|
| chrF mean | **0.7306** | 0.6869 |
| chrF std | 0.0716 | 0.0644 |
| Latency mean | 5.60 s | 5.54 s |
| Name recall | **1.0000** | 0.9615 |
| Length ratio | 1.0151 | 0.9953 |

Paired by excerpt: Index wins **25 of 28**, mean chrF delta **+0.0437**
(median +0.0409). The dev gap is therefore not a dev-set artifact.

A Claude-only blind pass on the 28 test pairs (14 per batch, tools disabled)
gives Index 18 wins, Q4 6, 4 ties; decisive win rate 75.0%, mean score 3.429
vs 2.893, mean difference +0.536, sign test p = 0.0227. The 95% bootstrap CI
for the score difference is +0.107 to +0.964, and the book-clustered CI stays
positive. Category counts are only four excerpts each: Q4 takes dialogue 3–1
and description 2–1; Index takes introspection 4–0, irony 3–0, terminology
3–0, long syntax 3–0 and action 3–1. The category split is too small to
overturn the overall result, but it is a reminder that Q4 is not uniformly
worse, especially in dialogue.

## Candidate smoke

### SalamandraTA-7B-instruct v3 Q4_K_M

Two prompt shapes were tested on the same five dev excerpts.

**Native chat prompt, no glossary/style.** Mean chrF **0.6729** on those five.
It translates cleanly and reads fluently, but this number is not directly
comparable to the production-prompt baselines; the production run below is the
gate. Outputs were complete, 92–259 tokens, 2.1–6.4 s. The GGUF includes a
ChatML template and stops correctly at `<|im_end|>`; using `raw /api/generate`
instead caused runaway continuation on three of five excerpts.

**Production glossary/style prompt.** Mean chrF **0.0883** on five dialogue
excerpts, with length ratios **5.3–15.1** and runaway continuation. The full
51-term glossary plus the 2.2k-character style block is not handled by this
translation-only model. It also showed European-Portuguese forms
("acalma-te") and translated the name "Chivalry" as "a cavalaria" (the
cavalry). That is a plot-level name error.

Verdict: **not admitted to the queue.** The native translation is promising,
but it fails the production prompt and the terminology gate. Reconsider only
with a dedicated adapter and a much smaller glossary/stop-token setup.

### EuroLLM-9B-Instruct Q4_K_M

Five dialogue excerpts with the production glossary/style prompt: mean chrF
**0.6870**, against Index 0.6971 and Q4 0.6634 on the same five. Latency was
1.5–5.6 s, faster than Index.

It follows the prompt and does not run away, but it fails the terminology
gate: it leaves "Raiders" and "coterie" in English, translates Skill as
"Habilidade" instead of "Talento", and uses European-Portuguese articles
before proper names ("o Verity", "o Will", "o Fitz"). It also writes "Tenho
aconselhado ela" in a colloquial register. The chrF is close to Index, but the
glossary and pt-BR register are not good enough for the queue.

Verdict: **not admitted.** No full dev run; the five-excerpt gate already
shows that it does not beat Index on the dimensions that matter.

### Seed-X-PPO-7B

Reserve; not tested. Third-party GGUF, no chat template, `<pt>` suffix and
beam search in the reference setup. With both admitted challengers failing the
smoke, there is no reason to take on that integration risk now.

## Error analysis

Both models produce publishable passages and both make serious mistakes. The
recurring failure modes are more useful than the aggregate score:

1. **Gender agreement.** Examples: "Verity esteja morta", "vou repreendê-la"
   for Fitz, "os dois" for Molly and Nettle. Index and Q4 both fail here; the
   error is not unique to the weaker model.
2. **English leakage and title calques.** "Wit-bond", "Skilling", "King
   Shrewd", "Watch Island", "King-in-Waiting" rendered as "Rei em Espera",
   "Regente" or "rainha-a-guarda". A glossary and a title table in the style
   prompt are mandatory.
3. **Place and dynasty names.** Buck/Farrow/Tilth left in English instead of
   Cervo/Vara/Lavra; "FitzChivalry Farseer" substituted for Chivalry or for the
   Farseer dynasty; "Farseer" substituted for King Wisdom. These are
   plot-level errors, not style preferences. In the held-out A/B, the largest
   Q4 penalties were exactly these FitzChivalry insertions.
4. **Lexical non-words and false friends.** "honres", "tapeçário",
   "discretões", "contevei"; "save" translated as "salvar"; "steams" as
   "estufas". A spell/consistency pass in refinement would catch most of these.
5. **Narrative voice.** One Q4 output rewrote a third-person historical
   passage as first-person Chivalry. That is a hard fail regardless of prose
   quality.

The practical conclusion: model choice reduces the frequency of these errors,
but does not remove the need for the review gate and the terminology probes.

## Decision

**Default local model: Index-Translate 9B Q4_K_M.**

Reasons: best chrF on dev and long chapters, best term compliance on the long
chapters, 47/56 paired dev wins, 25/28 paired test wins, and a consistent blind
preference from two independent judges on dev plus a Claude-only 18–6–4 pass
on the held-out test set. The COMET advantage is small and not significant, so
the claim is "best measured model", not "semantically superior in every
passage".

**Fallback: Hy-MT2 7B Q4_K_M.** Keep it installed. It is faster on long
chapters, has slightly better name recall on the dev short-excerpt metric
(0.9799 vs 0.9702; Index was better on the test set), and is competitive on
introspection/COMET. It is the right fallback if Index fails a book-specific
review or if latency matters more than terminology.

**Challengers:** SalamandraTA and EuroLLM were both rejected at the
five-excerpt smoke. SalamandraTA translates well with its native prompt but
fails the production glossary/style prompt; EuroLLM fails the
terminology/pt-BR gate. Seed-X remains a reserve because of the unofficial
GGUF and the no-chat-template/`<pt>` setup. No cloud model was used for the
local decision.

**Queue settings:** one book, one chunk, `--parallel 1`, stop at the review
gate. Do not lower the review gate because the model improved.

## Caveats

- Only Farseer has an official PT-BR reference; Gwynne and Abercrombie probes
  measure provisional-glossary consistency.
- One published reference per excerpt biases chrF and COMET toward that
  translator's choices. The blind A/B mitigates this, but it is still two LLM
  judges, not professional human reviewers.
- The test set has 28 excerpts; category-level conclusions are noisy.
- The 8 GB card is the ceiling. A 12B+ model would need offload and would not
  be comparable at book scale.
- COMET is reference-based and insensitive to some name/terminology errors that
  the probes catch.

## Reproduction

```bash
# dev, 3 repeats
python scripts/benchmark_fase_d.py \
  --corpus data/benchmark/literary/eval_farseer_dev.jsonl \
  --models hy-mt2-7b index-translate-9b --repeats 3 \
  --out-root data/benchmark/eval-dev

# probes, corrected combined file
python scripts/benchmark_fase_d.py \
  --corpus data/benchmark/literary/probes_run.jsonl \
  --models hy-mt2-7b index-translate-9b --repeats 1 \
  --out-root data/benchmark/eval-probes-rerun

# test, held out
python scripts/benchmark_fase_d.py \
  --corpus data/benchmark/literary/eval_farseer_test.jsonl \
  --models hy-mt2-7b index-translate-9b --repeats 3 \
  --out-root data/benchmark/eval-test

# blind sheet and normalized stats
python scripts/make_pairwise_sheet.py \
  --corpus data/benchmark/literary/eval_farseer_dev.jsonl \
  --run-dir data/benchmark/eval-dev --model-a hy-mt2-7b \
  --model-b index-translate-9b --out data/benchmark/eval-dev/judging.jsonl
python scripts/analyze_pairwise.py \
  --input data/benchmark/eval-dev/judgments-self-full.jsonl \
  --key data/benchmark/eval-dev/judging-key.json \
  --reference-model index-translate-9b

# COMET
docker exec -e HOME=/home/app \
  -e PYTHONPATH=/home/app/.local/lib/python3.11/site-packages comet-scorer \
  python scripts/score_comet.py \
  --corpus data/benchmark/literary/eval_farseer_dev.jsonl \
  --run-dir data/benchmark/eval-dev --model index-translate-9b
```
