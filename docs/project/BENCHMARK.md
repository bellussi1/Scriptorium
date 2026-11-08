# Literary benchmark: design and pilot results

The upstream benchmark is a solid multilingual smoke test, but it is not a
literary EN→PT-BR benchmark. It uses short public-domain passages, a generic
rubric and a single LLM judge. This project adds a separate literary track under
`benchmark/literary/`.

**Status:** harness implemented and run on the 50-excerpt context corpus. The
quantization round (Q4/Q6/Q8) is complete; Q4 remains the practical local choice.
The full *Howling Dark* translation completed (1,074/1,074 chunks, 0 failures)
and the EPUB passed deterministic validation and EPUBCheck after a source-role
repair. Full Phase 4 (cloud candidates, aligned references, blind human review)
still requires approval.

## 1. Method

### 1.1 Corpus

The local corpus is built from the user's EPUBs and stored under
`data/benchmark/literary/` (gitignored). No copyrighted excerpt is committed.

- Books: *Lonesome Dove* (McMurtry), *Assassin's Apprentice* (Hobb), *Howling
  Dark* (Ruocchio).
- 15 excerpts, 5 per book, 87–172 words each.
- Categories assigned by a deterministic heuristic: dialogue, introspection,
  description, long syntax, narration. These are **candidates**, not a final
  human-curated corpus.
- Selection is the first three long spine documents per book; it is not a
  random sample and over-represents chapter openings.
- No aligned Portuguese references were added in the pilot. Official PT
  editions exist for Farseer 1 and Sun Eater 1. The Lonesome Dove PT file is the
  user's own unreviewed draft and cannot be used as a gold reference; it can
  only support the user's revision.

Reproduce:

```bash
docker compose -f docker-compose.dev.yml exec app \
  python -m benchmark.literary.corpus \
  --inventory /app/data/calibre/targets.json \
  --out /app/data/benchmark/literary/corpus.jsonl \
  --book 311 --book 336 --book 430 --per-book 5
```

### 1.2 Controlled comparison

Each model gets a prompt appropriate to its training, plus a common glossary
round:

| Model | Prompt style | Context | Temperature | Max output |
|---|---|---|---:|---:|
| TranslateGemma 12B | Official single-user template, two blank lines before text | 4K | 0.0 | 1,200 |
| Qwen3 8B | Literary system prompt + source user message | 8K | 0.0 | 1,200 |
| Qwen3 14B | Same as Qwen3 8B | 8K | 0.0 | 1,200 |
| Hy-MT2 7B | Native terminology/personalization template | 8K | 0.7 (top_p 0.6, top_k 20, repetition 1.05) | 1,200 |
| Index-Translate 9B | English instTrans template with hard constraints | 8K | 0.0 | 1,200 |

TranslateGemma has no glossary in its native round because its fixed template
does not provide a clean place for one. For the other models, the glossary
round adds the same `Terminology (mandatory)` block. This asymmetry is recorded
in the run artifacts. The adapters use the official GGUF tags:
`hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M` and
`hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M`. The Index prompt is the
English instTrans template, because the Chinese template produced chat-style
analysis instead of translation under Ollama's chat endpoint. Both models ran at
8K context so the comparison reflects the 8 GB card; 16K was tested separately
and only added CPU offload.

### 1.3 Metrics

Deterministic, cheap, and explicitly not a verdict:

- **chrF** (character n-gram F2) when a reference exists;
- output/source **length ratio**;
- **number recall**;
- **name/term recall** against the glossary;
- **English leakage** (English stopword density in the output, excluding tokens
  that are also common Portuguese words such as `as`);
- **repetition ratio** (most frequent 6-gram / distinct 6-grams).

The decision layer is the six-dimension rubric in
[../LITERARY_RUBRIC.md](../LITERARY_RUBRIC.md), with blocking gates for
omissions, inversions, inventions, wrong language and structural corruption.
A high average cannot save a unit that fails a gate.

## 2. Pilot results

### 2.1 Coverage

| Model | Excerpts | Latency per excerpt | Output tokens | Status |
|---|---:|---:|---:|---|
| TranslateGemma 12B | 6 | 23–66 s | 152–226 | Complete |
| Qwen3 8B | 6 | 13–51 s | 167–260 | Complete |
| Qwen3 14B | 3 | 35–86 s | 164–218 | Complete |
| Hy-MT2 7B | 15 | 3.4–6.3 s | 151–277 | Complete |
| Index-Translate 9B | 15 | 3.4–12.2 s (cold load on the first) | 130–251 | Complete |
| Cloud models | 0 | — | — | Not called; no approval |

Single run. The generalist and Index runs use temperature 0; Hy-MT2 uses the
sampling recommended by its model card (temperature 0.7, top_p 0.6, top_k 20,
repetition_penalty 1.05). Latency includes model load when the model was cold.

### 2.2 What the outputs showed

These are short, targeted error notes; the full outputs stay in the gitignored
run directory.

**TranslateGemma 12B**

- Fluent, natural Portuguese; dialogue and introspection read well.
- **Critical semantic error:** “This pup’s for you” → “Este pedaço de pão é
  para você” (puppy → bread).
- **Narrator gender error:** a male first-person narrator became “nua” in a Sun
  Eater excerpt.
- **Invented fauna:** “roadrunners and stinging lizards” became “corujas-de-bico
  e lagartos-ferrugem”.
- **Weakened/incorrect image:** “sulled in the sky like a mule” → “pairando no
  céu como uma mula” (literal; the sulking/immobile sense is lost).
- Verdict: **fails the semantic gate** on this pilot. Good for short passages,
  not a primary novel engine.

**Qwen3 8B**

- Correctly translated “pup” as “filhote” and kept the male narrator.
- Natural introspection; better at some idiomatic movement than
  TranslateGemma.
- **Omission:** dropped the “roofless barn and patched-up corrals” clause in a
  long Lonesome Dove sentence.
- **Regional/fauna errors:** “roadrunners and stinging lizards” → “roadrunners
  e lagartos que picam”; “springhouse” → “casa da água”; “jug” → “odre”.
- **Concept error:** “fugue” → “estado de inconsciência” in the no-glossary
  round.
- Verdict: best installed throughput/quality trade-off, but **fails the
  integrity gate** on the long-syntax excerpt.

**Qwen3 14B**

- Better long-syntax preservation (it kept the roofless-barn clause) and some
  imagery (“um sorriso de desprezo encarnado”).
- **Critical reversal:** “He turned away from me” → “Ele se virou para mim”.
- **Garbled phrase:** “a man-sized portion of meat off the joint” → “uma porção
  do tamanho de um homem da carne do carcaço”.
- **Fauna errors:** “toadas cornudas”, “corredores de estrada”.
- Verdict: not a uniform improvement over 8B; much slower; **fails the semantic
  gate** on the reversal.

**Glossary round (Qwen3 8B and 14B, one Sun Eater excerpt)**

Adding `Fugue → Fuga` fixed the concept in both models:

- 8B: “Acordar de uma fuga nunca era fácil.”
- 14B: “Acordar da fuga nunca era fácil.”

`name_recall` reached 1.0 for the tested term. The rest of the excerpt still had
awkward literalism (“um lado de carne em um freezer”, “quase ser morto”),
which the source-aware reviewer must fix. This is evidence that the glossary
layer works and is not sufficient by itself.

### 2.3 Gate outcome

| Model | Semantic gate | Integrity gate | Terminology gate | Provisional status |
|---|---|---|---|---|
| TranslateGemma 12B | Fail | Fail | Fail (no glossary round) | Short-passage only |
| Qwen3 8B | Pass on 5/6 | Fail (omission) | Fail without glossary; improved with it | Baseline, not production |
| Qwen3 14B | Fail (reversal) | Pass on the 3 tested | Fail on fauna | Not clearly better |
| Hy-MT2 7B | No semantic reversal in the 3 reviewed; one verb-form error (`Convinci-me`) | Pass on 15/15 | Pass on the tested term, capitalization kept | Local candidate; needs editorial review |
| Index-Translate 9B | No semantic reversal in the 3 reviewed; typo `Convinquei-me` | Pass on 15/15 | Partial: recall 1.0, casing ignored | PT-BR post-edit required |

No tested model passes the production gate on this small pilot. That is the
correct result: a fluent output is not a passing output.

### 2.4 Hy-MT2 7B and Index-Translate 9B (2026-11-07)

Both official GGUF builds were installed and run on the same 15 excerpts with
the same pilot glossary. This is the first round with the specialized
translation models; it is not a final model choice.

| Model | Excerpts | Errors | Mean latency | Output tokens | Length ratio | Name recall | English leakage | Repetition |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Hy-MT2 7B Q4_K_M | 15/15 | 0 | 4.5 s | 3,000 | 0.983 | 1.0 | 0.0% | 0.9% |
| Index-Translate 9B Q4_K_M | 15/15 | 0 | 5.2 s | 2,629 | 0.998 | 1.0 | 0.0% | 0.9% |

The leakage metric now excludes `as`, which is both an English stopword and a
common Portuguese word; the earlier 0.7% / 0.5% figures were false positives from
that overlap. Recomputing the stored outputs with the corrected metric gives
0.0% for both models.

These are the re-run numbers after the final Ollama configuration (parallel 2,
8K, FA on, q8_0 KV). The first run, before the correct restart, measured 15.3 s
for Hy-MT2 and 9.9 s for Index; it is kept only in the gitignored artifacts and
in the git history. The configuration change is the reason the same 15 excerpts
now take 4.5-5.2 s instead of 10-15 s. The run directories are
`data/benchmark/literary/runs/20261107T231354Z/` (before) and
`.../20261107T235601Z/` (after); both are gitignored.

`name_recall` is based on the two excerpts where a glossary term actually
occurs. The mean latency includes cold loads; it is not a tokens/s benchmark.
With the final Ollama configuration (parallel 2, 8K, FA on, q8_0 KV), the
observed footprint is **5.49 GB / 100% GPU** for Hy-MT2 and **5.44 GB / 100%
GPU** for Index. The earlier 9.6 GB / 64% and 7.4 GB / 80% readings were taken
before the correct restart and are superseded. The numbers are hardware-specific
and vary with the Ollama scheduler.

**Hy-MT2 7B.** The strongest result of this round on terminology and grammar:

- It kept the glossary's capitalized `Fuga` in the Sun Eater excerpt.
- It produced `a médica` for the source's `the doctor ... herself`.
- It preserved the long Lonesome Dove sentence without dropping the
  roofless-barn clause.
- **Grammar is not flawless:** the first run produced `Convenci-me` correctly,
  but the re-run produced `Convinci-me` (should be `Convenci-me`). The form
  varies at the recommended temperature 0.7, so one good run is not proof.
- Residual issues: `Evening` became `A noite`; `roadrunners` became
  `tordos-corretores`; `horned toads` became `sapos com chifres`. These are
  lexical/regional choices that need a glossary and a reviewer, not structural
  failures.
- After the configuration fix it loads at 5.49 GB and 100% GPU, with a 3-run
  median of 49.1 tok/s. The earlier 9.6 GB / 64% reading was taken before the
  correct restart; memory is no longer the reason to reject it.

**Index-Translate 9B.** Often more fluid, but with language-quality errors that
block publication without review:

- It ignored the glossary's capitalization: `fuga` instead of `Fuga`.
- It produced the typo `Convinquei-me` (should be `Convenci-me`) in both runs.
- The first run also produced an agreement error: `segredos que, mesmo agora,
  não é seguro compartilhar`; the re-run fixed that particular sentence, which
  shows the errors are run-dependent.
- It rendered `roadrunners` as `corredores-de-strada`.
- It kept the long-syntax content and read naturally in dialogue, but the errors
  above are exactly the kind a deterministic language check and a human
  post-edit must catch.
- After the configuration fix it loads at 5.44 GB and 100% GPU, with a 3-run
  median of 43.5 tok/s. It is no longer clearly faster than Hy-MT2: the re-run
  means are 4.5 s vs 5.2 s for the same 15 excerpts.

**Provisional reading.** Hy-MT2 is the better candidate for terminology
fidelity, but the grammar advantage is not consistent: both produced a
verb-form error in the re-run. Both need a PT-BR post-edit and stronger
case-sensitive glossary enforcement. Neither passes the production gate on this
round, and the sample is too small to rank them confidently.

### 2.5 Context corpus and quantization round (in progress)

The original 15-excerpt pilot is too small to rank models. A second corpus now
covers **50 excerpts from 10 books in the active queue**:

- Hobb: *Assassin's Apprentice*, *Ship of Magic*, *The Mad Ship*, *Fool's Errand*;
- Ruocchio: *Howling Dark*, *Demon in White*, *Kingdoms of Death*, *Ashes of
  Man*, *The Lesser Devil*, *Queen Amid Ashes*.

The builder samples chapters and categories across each book instead of always
taking the first paragraphs. The corpus is local-only under
`data/benchmark/literary/corpus_context.jsonl`.

Quantization round: the official Hy-MT2 GGUF repository publishes Q4_K_M, Q6_K and
Q8_0, **not Q5_K_M**. Q6_K and Q8_0 are downloaded. The benchmark command
accepts the compiled glossary shape and the compiled YAML style preset:

```bash
python -m benchmark.literary.runner run \
  --corpus /app/data/benchmark/literary/corpus_context.jsonl \
  --models hy-mt2-7b hy-mt2-7b-q6 \
  --glossary /app/data/compiled/sun-eater-2-glossary.json \
  --style-file /app/data/compiled/sun-eater-2-style.yaml
```

The run was executed after the full *Howling Dark* translation released the GPU.
All three models completed without generation errors:

| Model | Context | GPU/CPU | Excerpts | Mean latency | Length ratio | Name recall | Number recall | Leakage | Repetition |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Hy-MT2 7B Q4_K_M | 8K | 100% GPU | 50 | 5.52 s | 1.0023 | 1.0 | 1.0 | 0.0% | 1.04% |
| Hy-MT2 7B Q6_K | 8K | 78% GPU / 22% CPU | 50 | 14.48 s | 1.0118 | 1.0 | 1.0 | 0.0% | 1.03% |
| Hy-MT2 7B Q8_0 | 4K | 67% GPU / 33% CPU | 5 | 35.69 s | 1.0021 | n/a | n/a | 0.0% | 0.86% |

**Reading.** Q4 and Q6 are indistinguishable on the deterministic quality metrics;
Q6 is 2.6× slower because its 7.9 GB footprint does not fit the 8 GB card at 8K.
Q8 is slower still and also offloads. The quantization round therefore does not
justify changing the primary model: **Q4_K_M remains the practical local
choice**. A human/blind quality round could still find a difference that these
metrics do not measure, but there is no throughput/VRAM case for Q6 or Q8 on this
hardware.

`runner report-blind` produces an anonymized review sheet and a separate A/B/C
key for that human round.

## 3. What the pilot teaches

1. **Fluency is not fidelity.** The most fluent model produced the most
   confident factual errors. The rubric must gate on meaning, not on how good
   the Portuguese sounds.
2. **Narrator gender is a real failure mode.** A cast/glossary block and a
   source-aware check are needed even for English→PT, where gender is usually
   explicit.
3. **Regional and technical vocabulary needs a glossary.** “Fugue”, “springhouse”,
   “roadrunner”, “chaparral” and “sull” are exactly the terms a generic model
   guesses.
4. **Model size is not monotonic.** 14B was slower and not uniformly better
   than 8B; a specialized 12B was fluent but less faithful. The final choice
   must be per-workload, not per-parameter count.
5. **Glossary injection works when the term is explicit.** It does not fix
   syntax, omission or voice.
6. **The existing refine would make this worse.** It would rewrite these drafts
   without seeing the source; a “more polished” wrong sentence is still wrong.

## 4. Limitations

- 15 excerpts; not the 12–20 controlled comparison the plan calls for. The
  Hy-MT2/Index round ran all 15, but only three outputs were read closely.
- No aligned PT-BR references; chrF is therefore absent from the pilot.
- No blind human panel; the error notes are a single reviewer's reading.
- Cloud models were not called; no paid key was used.
- Single run per model; no variance estimate. Sampling differs by model card
  (temperature 0 for most, 0.7 for Hy-MT2), so latency and output length are
  descriptive, not a controlled speed benchmark.
- The corpus is auto-selected; categories and some excerpts need human review.
- The benchmark does not yet measure chapter-to-chapter continuity; it measures
  isolated excerpts.

## 5. Phase 4 plan

1. **Curate the corpus:** 12–20 excerpts, at least two consecutive passages per
   book, with categories reviewed by hand. Add poetry/epigraph and a document
   fiction sample if present.
2. **Align references:** use the official PT editions for Farseer 1 and Sun
   Eater 1; align at paragraph/sentence level and record the alignment
   confidence. Do not use fan translations or the user's unreviewed Lonesome
   Dove draft as gold. The Lonesome draft can be evaluated separately as a
   revision aid, never as a reference standard.
3. ~~**Install/test Hy-MT2-7B and Index-Translate-9B**~~ **Done 2026-11-07.**
   Both official Q4_K_M GGUFs installed and tested on 15 excerpts at 8K. A 16K
   run was tested and rejected for the 8 GB card because it added CPU offload.
   See 2.4.
4. **Cloud round:** Gemini 3.8 Flash, DeepSeek V4.1 Flash (only with a privacy
   decision), GPT-6 Luna, Claude Haiku 5.5. Set a hard budget and log actual
   usage.
5. **Blind judging:** randomize model labels; use the six-dimension rubric with
   gates; one strong judge plus a human spot-check; report confidence and
   disagreement.
6. **Continuity test:** translate three consecutive chapters and check names,
   terms, POV, gender, chapter seams, omissions and repetition.
7. **Decision:** select a local winner and a cloud winner only if the quality
   gap survives the confidence interval. If the cheap model is within the
   interval, choose cheap.
