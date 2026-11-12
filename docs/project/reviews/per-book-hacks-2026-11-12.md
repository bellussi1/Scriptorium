# Per-book hacks inventory (prompt 6.1, 2026-11-12)

Scope: every place in `src/`, `scripts/` and the queue UI that names a book, a
book's terms or a book's file names. Test fixtures are listed but kept: they are
regression data, not behaviour. Method: `grep` for each book title, term that
has a hard-coded rule (Chantry, Fugue, Jaddian, Halfmortal, Red Company, Painted
Man, Escuridão Ululante, VALKA…), chapter file names (`NN_Chapter_N_…`) and
running headers. Classes:

- **(a) data**: the rule is a term, a title or a heading. It belongs in
  `literary-resources` (glossary, chapter-title map or a book-fixes file).
- **(b) general rule**: the logic is correct for any book, but a constant in it
  is book-specific (a series name, a running header). It needs a derived value.
- **(c) remove**: a duplicate of data that already exists, or a one-off fix that
  no longer applies.

## Inventory

| # | Where | What | Why it exists | Class | Effect on the next book |
| --- | --- | --- | --- | --- | --- |
| 1 | `src/literary/reading_repair.py:656-712` `_replace_terms_in_text`, `apply_sun_eater_terms` | About 25 hard-coded pairs (`Chantry→Chantria`, `Fugue→fuga`, `Jaddian→jaddiano`, `Halfmortal→Semimortal`, `Red Company→Companhia Vermelha`, `Painted Man→Homem Pintado`, `Normanda→normanda`, `Cielcin→cielcin`, …). Applied to **every** book (`apply_terms=True`). | Early fixes found by audits; the glossary was not yet the runtime source. | (a), and (c) for the pairs the glossary already holds as `forbidden` | A new book gets Sun Eater rules; a term that is not in the list (e.g. the lower-case `fugue` in Kingdoms) is not repaired. |
| 2 | `src/literary/reading_repair.py:728-760` `global_text_fixes` | `Escuridão Ululante→Uivante` (title), `VALKA CORREU NA DIREÇÃO DELE` (a Howling Dark sentence), `FEITO EM EUA→FEITO NOS EUA` (copyright, all books). | Defects seen in Howling Dark and its copyright page. | Howling sentence and title: (a). Copyright line: (b) | Howling sentences run on every book. |
| 3 | `src/literary/reading_repair.py:795-813` `HEADING_FIXES` (+ `fix_headings`, line 821) | 14 chapter-heading overrides keyed by file name, e.g. `87_Chapter_80_Halfmortal.xhtml: SEMIMORTAL`. | The body had untranslated or wrong headings. The file names are Howling Dark's (80 chapters). | (a), and duplicates `literary-resources/.../chapter-titles/*.yaml` where a title map exists | Applies to any book whose file names match. |
| 4 | `src/literary/reading_repair.py:901, 1072, 1224` | `"Outros livros de Christopher Ruocchio"` for the Also-by page. | Official PT name for the Also-by heading. | (b): a series-level string | Only for Sun Eater books; a different series gets the wrong heading. |
| 5 | `src/literary/chapter_headings.py:47` `EN_RUNNING_HEADER = "Hobb, Robin - Ship of Magic"` | The English running header the aligner strips. | Ship of Magic is the only book it was built for. | (b): derive from the English EPUB metadata | Any other book's running headers are not removed. |
| 6 | `src/literary/queue_insights.py:128, 138`; `queue-manager.js:1409`; `queue.json` key `quality_chantry` | A "Chantry remaining" metric and flag in the Queue UI. | Chantry was the Demon in White defect. | (a): replace with a generic "forbidden forms remaining" count from the glossary | Shows a Demon-only metric on every book. |
| 7 | `src/literary/chapter_titles.py:16-18` (docstring) | Example command with Demon's Chantry edit. | Documentation. | (c) | None (text only). |
| 8 | `scripts/audit_book.py:17`, `scripts/db_snapshot.py:9` (docstrings) | Example arguments naming Howling Dark. | Documentation. | (c) | None (text only). |
| 9 | `src/literary/polish.py:144` | Skips books that are not Sun Eater. | Series gate for the reader pass. | (b): keep, but read it from the series field | Correct for now; a new series needs the gate to be data-driven. |
| 10 | `tests/literary/fixtures/golden/{caron_ch24, chantry_ch76, vesperad_ch58, vesperad_keep}` | Regression fixtures from the defects that escaped. | Golden set (prompt 3.3). | Keep (tests) | None. |

## What still stops the next book from running without a patch

1. Rules 1–3 are applied to every book. A new book with a new term or a new
   heading gets no repair, and the forbidden form then fails the audit. The fix
   is to read the repair pairs from the book's compiled glossary (its
   `forbidden` → `target` pairs) and to move Howling-only rules into a
   per-book data file.
2. The chapter-title map is written by hand for each book (the post-pass cannot
   run without it). Prompt 6.3 covers this.
3. The Queue UI shows a Chantry metric (rule 6).
4. The running-header constant (rule 5) and the series string (rule 4) assume
   Ship of Magic and Sun Eater.

## Concrete defects found while writing the inventory

- Rule 1 lacks `fugue` in lower case. Kingdoms of Death left 19 English
  `fugue` words in the translation; they were fixed by a gated post-pass on
  2026-11-12. The repair would not have caught them.
- `Legion` and `Imperial Legion` are rendered as `legionário(s)` in several
  Kingdoms chapters. The glossary target is `Legião`; the audit counts a miss.
  This is a glossary-policy choice, not a repair rule.

## Status after prompt 6.2

Moved to `literary-resources/christopher-ruocchio/sun-eater/reader-repairs.yaml`:

- Rule 1: the 12 phrases, 14 terms and 2 casing pairs (now data, same values as
  the code had, extracted with `ast`). Added `fugue → fuga` (any case).
- Rule 3: the 14 headings, keyed by the queue's book title. The repair receives
  `queue_title` from the queue runner and from polish; it cannot use the EPUB's
  own title, which is already translated.

Still in code (next steps):

- Rule 2: `global_text_fixes` (Howling sentences, copyright line, Chantry casing).
- Rule 4 (series string) and rule 5 (`EN_RUNNING_HEADER`).
- Rule 6: the Chantry metric in the Queue UI.
- Heading override for `VALKA CORREU NA DIREÇÃO` in `fix_headings`, if any.

## Status after the second 6.2 pass (2026-11-12, branch `refactor/prompt-6-2-data`)

Moved to data:

- Rule 2: Howling Dark's sentence and title fixes are `book_text_fixes` in
  `reader-repairs.yaml`, applied only to that queue title. The copyright lines stay in code
  (class b: they hold for every book).
- Rule 4: the front, back and extra matter labels are `labels` in `reader-repairs.yaml`;
  the document-title helper uses the same labels.
- Rule 5: the Ship of Magic running header is `running_header` in its chapter-title spec.
- Rule 6: the Chantry, Cielcin, Mericanii and Halfmortal metrics are one count,
  `forbidden_forms`, of the reader's term and casing sources; the UI row and the locale keys
  follow it.
- Generic term casing: `reader_terms` now apply to every case variant, not only the
  exact-case form.

Still in code, by design: the copyright lines (class b), the Sun Eater series gate in
`polish.py` (class b), and the docstring examples (class c).

