# Review — Ship of Magic (pt-BR)

- **Date:** 2026-11-09
- **Book:** *Ship of Magic*, Robin Hobb — *The Liveship Traders* #1
- **Artifact:** `translated_files/Ship of Magic (pt-BR).refined.epub`
- **Verdict:** **not approved** for the Kindle library
- **Queue state:** `completed` in the database, but `reviewed_at` is empty; the
  new review gate displays it as `needs_review` and excludes it from the Kindle
  export. The previous UI approval (2026-11-09 03:04) predates the review gate
  and is treated as invalid.

## Evidence

| Check | Result |
|---|---|
| Pair validation | passed (0 blocking issues) |
| EPUBCheck | **24 errors**, 0 fatals, 0 warnings |
| Refine | 1 of 12 documents refined; 11 skipped (`spine_count_mismatch`, `paragraph_count_mismatch`) |
| Flags | 116 flagged, 116 attempted, 39 accepted, 77 rejected |
| Text | 308,725 words, 8,692 paragraphs, 13 documents |
| Placeholder artifacts | none (`[id`, `[[`, `{{` absent) |
| Source page footers | **290** `file:///...` occurrences |
| Running headers | **295** repeated `Hobb, Robin - Ship of Magic`-style lines |
| Quotes | 287 straight double quotes vs 5,204/5,226 curly |
| TOC | 1 entry |
| English leakage | at least 2 substantial paragraphs remain in English |

The `file:///` lines and the running headers are inherited from the Calibre
source EPUB, which is an HTML print conversion. The translation preserved them.
The English paragraphs are a translation gap, not a source artifact; one is the
"By the time the Reaper reached Bingtown..." passage.

EPUBCheck errors include `img` without `alt`, invalid `h1`/`ul` nesting in the
nav document, NCX `playOrder`, undefined fragment identifiers, EPUB2 metadata
using EPUB3 `meta` attributes, missing `guide/reference`, and a missing
unique-identifier. Most are inherited from the source; they still fail the
review gate.

## Why it is not ready

1. A reader would hit page footers, URLs and repeated running headers throughout
   the book.
2. At least two English paragraphs remain untranslated.
3. Dialogue typography is inconsistent (straight vs curly quotes).
4. The EPUB is structurally invalid in 24 places and has a one-entry TOC.
5. The refine pass covered only one document, so the selective refinement did
   not review the rest of the book.

## Required before approval

- Strip source page headers/footers (`file:///...`, repeated `Hobb, Robin - ...`
  lines) and normalize the title variants.
- Normalize dialogue quotes/travessões consistently.
- Find and re-translate every paragraph still in English; rerun the language
  audit.
- Fix the EPUBCheck errors and build a chapter-level TOC.
- Re-run the review and approve only after the checks pass.

## Note on the rest of the queue

The review gate is now enforced for every finished book. *Howling Dark* is also
`completed` with an empty `reviewed_at`; it is excluded from the next Kindle
build until explicitly approved. The Mad Ship, currently translating under the
old runner, will also land in review even if its machine gate passes.
