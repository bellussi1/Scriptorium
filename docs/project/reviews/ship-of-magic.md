# Review — Ship of Magic (pt-BR)

- **Date:** 2026-11-09
- **Book:** *Ship of Magic*, Robin Hobb — *The Liveship Traders* #1
- **Artifact:** `translated_files/Ship of Magic (pt-BR).refined.epub` (repaired in place)
- **Backup:** `data/backups/ship-of-magic/Ship of Magic (pt-BR).refined.pre-repair.epub`
- **Verdict:** **approved** for the Kindle library after the targeted repair
- **Queue state:** `completed`, `reviewed_at` set (2026-11-09T07:27:31Z)

## Repair

The source is a PDF-to-HTML conversion, so the translation carried the page
furniture. The generic Sun Eater reader pass cannot be applied to it: that pass
assumes `_Chapter_` files and the Sun Eater front matter. The targeted repair
fixed the deterministic blockers:

| Check | Before | After |
|---|---|---|
| EPUBCheck | 24 errors | **0 fatals / 0 errors / 0 warnings** |
| Pair validation | passed | passed, 0 blocking (one TOC-label length warning) |
| Source page footers | 290 `file:///` | **0** |
| Running headers | 295 lines | **0** (447 header lines/title variants stripped) |
| Straight double quotes in text | 287 | **0** |
| Placeholder artifacts | 1 `[/id1]` | **0** |
| English paragraphs | 2 substantial | **0** above the 30% stopword threshold |
| TOC | 1 entry | **11 part entries** |

The two English paragraphs were translated with the book's model and the
surrounding names were preserved (`Reaper`, `Bingtown`); two wording fixes were
applied (`o Reaper`, `os reparos`). The EPUB2 metadata, unique identifier,
guide, image `alt`, NCX identifier/playOrder and the dead
`index_split_011.html` outline page were fixed. The 11 TOC entries are parts,
not chapter titles: the source has no chapter headings to rebuild from. This is
the remaining structural limitation and the reason the approval is human.

The full selective refine remains 1 of 12 documents: the source/draft spine and
paragraph counts differ, so the refine runner skips the rest. The actual
untranslated gaps were the two paragraphs above; the rest of the prose was
already translated. The human approval accepts that limitation.

## Evidence

- Backup of the pre-repair artifact: see above.
- Kindle export: `Robin Hobb/The Liveship Traders/01 - Ship of Magic (pt-BR).epub`.
- The repaired artifact is the one selected by `best_artifact`; the older
  `fixed`/`fixed-v2` files remain as historical artifacts.

## Note on the rest of the queue

*Howling Dark* was approved first (2026-11-09T07:14:19Z). *The Mad Ship* remains
paused and outside the Kindle library.
