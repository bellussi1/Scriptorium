# Literary benchmark: design and pilot results

The upstream benchmark is a solid multilingual smoke test, but it is not a
literary EN→PT-BR benchmark. It uses short public-domain passages, a generic
rubric and a single LLM judge. This project adds a separate literary track under
`benchmark/literary/`.

**Status:** harness implemented; pilot run on models already installed. Full
Phase 4 (Hy-MT2, Index-Translate, cloud candidates, aligned references, blind
human review) still requires approval.

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
| Hy-MT2 7B | Native instruction prompt | 8K | 0.0 | 1,200 |
| Index-Translate 9B | Chinese-centric translation prompt + glossary | 32K | 0.0 | 1,200 |

TranslateGemma has no glossary in its native round because its fixed template
does not provide a clean place for one. For the other models, the glossary
round adds the same `Terminology (mandatory)` block. This asymmetry is recorded
in the run artifacts. The `hy-mt2:7b` and `index-translate:9b` entries in
`benchmark/literary/adapters.py` are placeholders; replace them with the actual
Ollama/llama.cpp tags after installation.

### 1.3 Metrics

Deterministic, cheap, and explicitly not a verdict:

- **chrF** (character n-gram F2) when a reference exists;
- output/source **length ratio**;
- **number recall**;
- **name/term recall** against the glossary;
- **English leakage** (English stopword density in the output);
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
| Hy-MT2 7B | 0 | — | — | Not installed |
| Index-Translate 9B | 0 | — | — | Not installed |
| Cloud models | 0 | — | — | Not called; no approval |

All runs are at temperature 0, single run. Latency includes model load when the
model was cold.

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

No tested model passes the production gate on this small pilot. That is the
correct result: a fluent output is not a passing output.

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

- 15 excerpts, only 6/3 used in the pilot; not the 12–20 controlled comparison
  the plan calls for.
- No aligned PT-BR references; chrF is therefore absent from the pilot.
- No blind human panel; the error notes are a single reviewer's reading.
- No Hy-MT2, Index-Translate or cloud models; no large download or paid call was
  authorized.
- Single run at temperature 0; no variance estimate.
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
3. **Install/test Hy-MT2-7B and Index-Translate-9B** after explicit download
   approval. Test 4K and 8K contexts; record VRAM and tokens/s.
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
