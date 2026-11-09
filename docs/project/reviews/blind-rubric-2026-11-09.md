# Blind A/B rubric — Q4 vs Index

Use this sheet without looking at `judging-key.json`. The key is stored
separately and must stay closed until both judges finish.

## What the judge sees

For each row:

- `source`: the English excerpt;
- `reference_pt`: the official PT-BR paragraph (Farseer only; empty for
  Gwynne/Abercrombie probes);
- `output_a` and `output_b`: two anonymous translations, order randomized.

## Scores (1–5)

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Terminology / names | wrong name, wrong glossary term, or a plot-level substitution | mostly right, one weak term | every term and name correct, gender/case natural |
| Fidelity | omission, addition, inversion, or invented content | meaning preserved, one ambiguous clause flattened | meaning, ambiguity and implication preserved |
| Prose / readability | MT syntax, unnatural pt-BR, repetition | readable but uneven | reads as literary pt-BR, rhythm and syntax controlled |
| Voice / register | wrong narrator or character voice | mostly consistent, some flat passages | distinctive voice, dialogue and register preserved |
| Mechanics | agreement, punctuation or truncation problems | minor issues | clean grammar, punctuation and formatting |

**Terminology is a gate, not an average.** A wrong character name or a
glossary term that changes the plot caps that output at 2 for the overall
preference, even if the prose is beautiful.

## Preference

After the five scores:

- `a` — A is better for a reader;
- `b` — B is better for a reader;
- `tie` — genuinely equivalent, or both fail in the same way.

If the prose winner and the fidelity winner differ, prefer the one that
preserves names/meaning and note the trade-off. Do not reward fluency that
changes the story.

## Output format

One JSON object per row:

```json
{"id": "...", "score_a": 4, "score_b": 3, "preference": "a",
 "term_a": 5, "term_b": 3, "fidelity_a": 4, "fidelity_b": 3,
 "prose_a": 4, "prose_b": 4, "voice_a": 4, "voice_b": 3,
 "mechanics_a": 5, "mechanics_b": 4,
 "notes": "A keeps Torre do Cervo and Regal; B swaps Regal for FitzChivalry."}
```

## Judge hygiene

- Do not infer the model from style or from the order; A/B is randomized.
- Judge each row independently; do not carry a running score.
- Quote only short evidence in `notes`, never long copyrighted passages.
- If a row is misaligned or the reference is clearly wrong, write
  `"notes": "alignment suspect"` and do not let it decide the comparison.
- Two judges: the repository agent (DeepSeek) and a Claude model. Compare
  their win rates; review the rows where they disagree instead of averaging
  the disagreement away.
