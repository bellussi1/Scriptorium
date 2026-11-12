# New-book onboarding checklist (prompt 6.3)

Run before a book is queued. Every item has a command or a file that proves it.
The dry run uses `queue plan` (read-only). `queue run --dry-run` only accepts
pending or paused books, so it cannot be used for a book already reviewed or
translating.

## Checklist

| # | Item | Proof | Kingdoms of Death (dry run, 2026-11-12) | Ashes of Man |
| --- | --- | --- | --- | --- |
| 1 | Resources validate | `python -m src.literary.cli resources validate` | pass (43 files) | pass |
| 2 | Series and index in the queue | `queue plan --book-id N`, `book.series` / `series_index` | The Sun Eater 4.0 | The Sun Eater 5.0 |
| 3 | Source EPUB exists in the library | `queue plan`, `source_path` | present | present |
| 4 | Model installed | `ollama list` | Index-Translate-9B Q4_K_M | same |
| 5 | Glossary compiled | `queue plan`, `glossary.terms` | 126 terms | 128 terms |
| 6 | Glossary forbidden forms | `queue plan`, `glossary.forbidden_terms` | 8 | 8 |
| 7 | Official terms checked against the PT edition | `confidence` in `glossary.yaml` (series) | **gap**: 24 of 29 series terms are `provisional`, 3 `confirmed`, 2 `reviewed` | **gap**: same series glossary |
| 8 | Style block | `style.yaml`, `queue plan`, `style.translation` | present | present |
| 9 | Plan has no issues | `queue plan`, `issues` | none (after `622fa92`) | none |
| 10 | Chapter-title map for the post-pass | `literary-resources/.../chapter-titles/<slug>.yaml` | present (51 chapters) | **missing** |
| 11 | Reader-repair headings | `literary-resources/.../reader-repairs.yaml`, `headings` | not needed | not needed |
| 12 | Gates defined | `scripts/audit_book.py` thresholds: pair and EPUBCheck 0 errors, forbidden 0, glossary coverage ≥ 0.9 overall and ≥ 0.8 per file, length ratio 0.8–1.2 | defined | defined |
| 13 | Audit sample with a cloud judge | `--max-cloud-usd` cap | not run (no approved cap) | not run |
| 14 | Acceptance criteria written | the audit reasons and the review checklist above | defined | defined |

## What is missing for Ashes of Man

1. Official terms (item 7). Only the terms with `confirmed` or `reviewed` are
   verified; 24 series terms are provisional. The translation runs with them.
2. The chapter-title map (item 10). The post-pass cannot run without it. It is
   written by hand from the English titles and the PT edition's conventions.
3. The series glossary is shared with every Sun Eater book, so a term fixed for
   one book changes all of them. That is intended, but it should be reviewed
   once for the whole series.

## What the Kingdoms dry run showed

- The plan resolves completely. Its only error was a resource-schema collision
  introduced by the reader-repair data file (`622fa92` fixes it).
- The gate that failed on Kingdoms (one chapter below 0.8 glossary coverage)
  is a glossary-policy question, not a checklist item: `Legion` is rendered as
  `legionário(s)` in chapter 15, and an unmarked adjective `Sollan` appears
  there too. Both need a glossary decision (an alias or a term rule), not a
  repair.

## Not covered by this checklist

- Cloud judge sampling (item 13): needs an approved cap per run.
- The Queue UI check for the book (the book appears, Run is enabled): needs the
  app and the agent running.
