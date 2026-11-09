# New short series: language audit, skeletons and queue

Date: 2026-11-09

## Request

Add the five book-1 EPUBs to the translation queue and create a lean series
skeleton plus book-1 resources. John Gwynne and Joe Abercrombie need a shared
world glossary, not isolated per-series glossaries.

## Language audit

The Calibre language column is not reliable for this batch. The EPUB body and
`dc:language` were checked directly.

| Series | Book 1 | Calibre | Body | Decision |
|---|---|---|---:|---|
| The Faithful and the Fallen | Malice | 354 | English | Queued |
| Of Blood and Bone | A Time of Dread | 345 | English | Queued |
| The Age of Madness | A Little Hatred | 346 | English | Queued |
| The Licanius Trilogy | The Shadow of What Was Lost | 264 | pt-BR | Not queued |
| The Dandelion Dynasty | The Grace of Kings | 292 | pt-BR | Not queued |

- **The Licanius Trilogy**: all three library EPUBs (264, 291, 261) have
  Portuguese bodies. Calibre labels some as English, but the text opens with
  “A Sombra do Que Foi Perdido” and Portuguese chapter titles. There is no
  English source in the library; acquiring one is a prerequisite.
- **The Dandelion Dynasty**: the individual files (292, 294, 293, 290) also
  have Portuguese bodies despite the metadata. The English source is the
  omnibus **Calibre 342**, 1,178,595 words. It must be split into four novels
  and validated before The Grace of Kings can be queued.
- Do **not** run a Portuguese body through the English→pt-BR pipeline.

## Queue

The three English books were queued at the tail, after Malazan:

| Priority | Book | Series | Calibre |
|---:|---|---|---:|
| -13 | Malice | The Faithful and the Fallen | 354 |
| -14 | A Time of Dread | Of Blood and Bone | 345 |
| -15 | A Little Hatred | The Age of Madness | 346 |

The UI now shows 28 books. The active *Fool's Errand* job was not interrupted.

## Resources

### John Gwynne — the Banished Lands

- `john-gwynne/the-banished-lands/glossary.yaml`: shared world terms
  (Banished Lands, the Faithful, the Fallen, Ben-Elim, Kadoshim, Otherworld,
  giant, wyrm, draig, wolven, White-Wing, starstone and places). Terms that
  only appear in Of Blood and Bone carry `first_appearance: a-time-of-dread`
  to keep them out of Malice's prompt.
- `.../series.yaml`: seven books, Faithful 1–4 then Of Blood and Bone 1–3.
- `.../the-faithful-and-the-fallen/`: Malice style measured from the first ten
  content documents (24,206 words; median 9; p90 22; 56.1% dialogue paragraphs)
  and 21 main-cast entries.
- `.../of-blood-and-bone/`: A Time of Dread style (24,839 words; median 12;
  p90 30; 36.8% dialogue paragraphs) and 15 main-cast entries.
- All Gwynne terms are provisional: no official PT-BR edition was verified.

### Joe Abercrombie — the First Law

- `joe-abercrombie/the-first-law/glossary.yaml`: shared world terms anchored on
  the Portuguese edition of *The Blade Itself* (Calibre 39): A União, O Norte,
  Inquisição, comedores, Magos, Primeiro dos Magos, Conselho Fechado, Conselho
  Aberto, A Casa do Artífice, O Nove Sangrento, os Lugares Altos, cabeças-
  achatadas, shankas. Terms not confirmed there are provisional.
- `.../series.yaml`: the PT-BR First Law trilogy (terminology canon) plus the
  three English Age of Madness novels.
- `.../the-age-of-madness/`: A Little Hatred style (21,101 words; median 9;
  p90 21; 54.9% dialogue paragraphs; 0 semicolons/1,000) and 12 cast entries.
- Age-specific terms: Breakers → Quebradores, Burners → Incendiários,
  The Weaver → O Tecelão, Valbeck kept, The Long Eye → O Olho Longo. All
  provisional.

### Series skeletons without English sources

- `james-islington/the-licanius-trilogy/series.yaml` records the pt-BR bodies
  and the missing English source.
- `ken-liu/the-dandelion-dynasty/series.yaml` records the pt-BR bodies and the
  English omnibus 342 as the source to split.

No glossary or style was created for these two; doing so would imply a
translation source that does not exist.

## Verification

- `resources validate`: **39 files, passed, no issues**.
- `pytest tests/literary/test_run_plan.py tests/literary/test_queue_runner.py`:
  **14 passed**.
- `build_run_plan` for the queued books: Malice 38 prompt terms / 8 style
  rules; A Time of Dread 42 / 8; A Little Hatred 41 / 8; no issues.
- `container_source` maps all three host paths to `/library/...`; `host_source`
  finds the files.
- All three are pending after Malazan in the UI.

## Next

1. Automated candidate-term extraction for Realm of the Elderlings and Sun
   Eater, then curation and `resources validate`.
2. Sample translation of three excerpts per book when the GPU is free; only
   then release The Mad Ship and Demon in White.
3. Malazan glossary and style.
4. Split the Dandelion boxset 342 if the English series is to be translated.
5. Acquire an English Licanius source before creating resources for it.
