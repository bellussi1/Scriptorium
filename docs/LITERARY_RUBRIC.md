# Literary translation rubric (EN → PT-BR)

**Version:** `lit-v1`
**Use:** evaluation of model outputs and human-reviewed chapters in this
project. It supersedes generic MQM only for the literary decision; MQM remains
useful for error analysis.

## 1. Dimensions and weights

| Dimension | Weight | What it measures |
|---|---:|---|
| Semantic fidelity | 25% | Meaning, implication, ambiguity, no omission/inversion/invention |
| PT-BR prose quality | 25% | Natural syntax, idiom, rhythm, punctuation, no calque/anglicism |
| Stylistic preservation | 20% | Voice, register, distance, sentence tendency, imagery, irony, repetition |
| Terminology and continuity | 15% | Names, invented terms, titles, forms of address, cross-chapter consistency |
| Dialogue and character voice | 10% | Speech tags, register, interruptions, idiolect, who is speaking |
| Integrity and completeness | 5% | Paragraphs, numbers, placeholders, notes, links, structure |

Weights are a starting proposal. For a specific book, the editorial team may
adjust them **before** scoring, not after seeing the results.

## 2. Anchored scale (1–10)

| Score | Anchor |
|---:|---|
| 10 | Published literary translation by a recognized translator; effectively unreachable by an LLM |
| 9 | Excellent professional translation; publishable with light editing; quibbles are stylistic |
| 8 | Very good; full meaning and tone, 1–2 minor losses |
| 7 | Good; 2–3 notable register/idiom/terminology problems; a reader misses something |
| 6 | Comprehensible but clumsy; multiple problematic choices |
| 5 | Usable only with editorial intervention; real meaning errors or fluency breaks |
| 4 | Significantly impaired; frequent contresens or sentence breakdowns |
| 3 | Passages incomprehensible or radically distorted |
| 2 | Mostly wrong; hallucinations dominant |
| 1 | Non-translation: wrong language, source copied, refusal, empty |

Without a published reference in front of the judge, cap `overall` at 9.0.
Reserve 9.5–10 for a comparison against a published human translation.

## 3. Blocking gates

A unit **fails** regardless of its average if any of these is present:

| Gate | Examples | Action |
|---|---|---|
| Critical omission | A clause, paragraph, named entity or negation dropped | Reject; retranslate/review |
| Meaning inversion | “He turned away” → “he turned toward”; “pup” → “bread” | Reject |
| Invention | A named entity, number, place or fact not in the source | Reject |
| Wrong language | Source language left untranslated at scale; wrong target variant | Reject |
| Structural corruption | Placeholder/tag loss, broken XHTML, TOC label glued/truncated, missing chapter | Reject |
| Terminology violation | Approved term replaced by a forbidden rendering | Reject or review |
| Narrator/POV shift | First person becomes third, narrator gender changes, speaker attribution changes | Reject |

A gate failure is recorded with the evidence (source span, target span, rule).
The average score is still reported for diagnosis, but the unit is not
“passed”.

## 4. Penalty table

Start each dimension at 10 and deduct. Multiple issues compound within a
dimension; cap at 1.

### Semantic fidelity

| Issue | Penalty |
|---|---:|
| Contresens / key-sentence reversal | −2.0 |
| Hallucinated fact/name/number | −2.0 |
| Significant omission (clause/entity) | −1.0 |
| Untranslated source span | −1.5 |
| Specialized term wrong | −0.5 to −1.0 |
| Minor semantic drift | −0.3 |

### PT-BR prose

| Issue | Penalty |
|---|---:|
| Grammar error breaking the sentence | −1.5 |
| Machine-translated/Anglicized construction | −0.5 to −1.0 |
| Calque with a native equivalent | −0.5 |
| Wrong target punctuation convention | −0.3 |
| Unnecessary subject pronoun / pronoun inconsistency | −0.3 to −0.5 |
| Pseudo-archaism not in the source | −0.5 to −1.0 |

### Stylistic preservation

| Issue | Penalty |
|---|---:|
| Signature rhetorical device lost (irony, parallelism, archaic register) | −1.0 to −1.5 |
| Deliberate repetition “fixed” into synonyms | −1.0 |
| Register flattened | −0.5 to −1.0 |
| Period-inappropriate vocabulary | −1.0 |
| Voice/rhythm homogenized across POVs | −0.5 to −1.0 |

### Terminology and continuity

| Issue | Penalty |
|---|---:|
| Approved name/term changes between chapters | −1.5 |
| Forbidden rendering used | −1.0 |
| Name split or translated against the glossary | −1.0 |
| Inconsistent form of address | −0.5 |
| First-appearance/spoiler violation | −0.5 |

### Dialogue and character voice

| Issue | Penalty |
|---|---:|
| Speaker attribution changed | −2.0 |
| Two characters’ voices become indistinguishable | −1.0 |
| Speech tag/register wrong for the scene | −0.5 |
| Interruption/ellipsis completed or explained | −0.5 |
| Dialogue punctuation broken | −0.3 |

### Integrity and completeness

| Issue | Penalty |
|---|---:|
| Missing paragraph | −2.0 |
| Placeholder/tag lost or duplicated | −2.0 |
| Number/date changed | −1.5 |
| Note/link broken | −1.0 |
| TOC label corrupted | −1.0 |
| Extra content not in the source | −1.0 |

## 5. Overall score

`overall` is holistic, not the weighted average. It must satisfy:

- if semantic fidelity < 6.0 → overall ≤ 6.0;
- if PT-BR prose < 5.0 → overall ≤ 6.0;
- if any dimension ≤ 3.0 → overall ≤ 4.0;
- overall should not exceed the minimum of the three primary dimensions
  (semantic, prose, style) by more than 0.5;
- a blocking gate makes the unit **fail**, whatever the number.

## 6. Blind comparison

1. Randomize candidate order; hide model/provider labels.
2. Score each candidate independently before comparing.
3. For a pair, ask “which is better and why?” only after independent scores.
4. Use at least two judges when the decision is close: one strong LLM judge and
   one human spot-check. Record disagreement.
5. Do not let a judge score its own model family without disclosure; prefer a
   different family or a human for that pair.
6. Re-score 3 earlier units every 50 evaluations; if the overall drifts more
   than ±0.5, recalibrate.

## 7. Confidence

Every report states:

- **high** — full passage, source and reference available, two independent
  judges agree within 0.5;
- **medium** — source available, one judge plus human spot-check, no reference;
- **low** — excerpt only, no reference, one judge; use for triage, not for a
  final purchase decision.

## 8. Report template

```markdown
## Unit <id> — <book>, <chapter>
Category: dialogue | introspection | description | action | long syntax | ...
Gate: pass | fail (<gate>)
Confidence: high | medium | low

| Dimension | Candidate A | Candidate B | Notes |
|---|---:|---:|---|
| Semantic fidelity |  |  |  |
| PT-BR prose |  |  |  |
| Stylistic preservation |  |  |  |
| Terminology/continuity |  |  |  |
| Dialogue/voice |  |  |  |
| Integrity |  |  |  |
| **Overall** |  |  |  |

Critical errors:
- ...

Preference: A | B | tie
Rationale (≤120 words):
...
```

## 9. What this rubric refuses

- A high average that hides a critical omission.
- “It reads well” as a substitute for fidelity.
- A judge score as objective truth.
- A single excerpt as proof of a model's novel-level quality.
- A style preference presented as an error.
