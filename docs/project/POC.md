# Proof of concept: what was actually built and tested

This document distinguishes **implemented and executed** from **planned**. No
cloud API was called. On 2026-11-07 the user authorized a metadata-only Calibre
update, which was applied through `calibredb` with a backup; the original EPUB
files were not rewritten. Two local Apache-2.0 models were downloaded and tested:
Hy-MT2-7B and Index-Translate-9B (about 10 GB total).

## 1. Implemented

### 1.1 Literary layer

| File | What it does |
|---|---|
| `src/literary/calibre.py` | Read-only Calibre SQLite inventory; authors, series, languages, formats, identifiers; EPUB scan; duplicate/bilingual classification |
| `src/literary/epub.py` | EPUB metadata/TOC/text extraction; structural validation; safe metadata rewrite |
| `src/literary/resources.py` | Hierarchical YAML loader/validator/compiler; glossary/style merge; first-appearance filtering |
| `src/literary/glossary.py` | Alias-aware, forbidden-aware, budgeted per-chunk selection and prompt block |
| `src/literary/queue.py` | Persistent SQLite book/chapter queue; states; idempotency; events |
| `src/literary/cost.py` | Dated pricing registry; measured token ratios; scenarios A–E |
| `src/literary/validation.py` | Pair and EPUB validation, including TOC-label corruption |
| `src/literary/cli.py` | Inventory, resources, queue, estimate, validate, metadata |
| `benchmark/literary/` | Local corpus builder, model adapters, metrics, runner/report |

### 1.2 Upstream integration

- `src/core/glossary/cli_loader.py` reads and preserves `forbidden`.
- `src/core/glossary/injector.py` renders forbidden renderings while keeping
  byte-identical output when none are present (upstream regression test passes).
- `docker-compose.dev.yml` builds the local source, binds Calibre read-only,
  binds the app to `127.0.0.1`, reaches host Ollama and runs as UID 1000 with a
  read-only root filesystem and dropped capabilities.
- `deployment/Dockerfile.dev` installs runtime + test dependencies and copies
  the test/benchmark/script resources.

### 1.3 Editorial resources

- `literary-resources/global/pt-br-conventions.yaml`.
- Lonesome Dove: series, glossary, style.
- Realm of the Elderlings: series, characters, glossary, universe style and
  five subseries style profiles (Farseer sampled; the other four explicitly
  provisional).
- Sun Eater: series, characters, worldbuilding, glossary, style.
- `docs/project/EDITORIAL_PROFILES.md`: evidence, metrics, labels and limits.

## 2. Executed tests and results

### 2.1 Docker

```bash
docker compose -f docker-compose.dev.yml build
docker compose -f docker-compose.dev.yml up -d
curl http://127.0.0.1:5000/api/health
```

Result: image built; container started; `/api/health` returned HTTP 200;
the app connected to host Ollama and listed all seven installed models.

### 2.2 Test suites

Inside the dev container:

```bash
pytest -p no:cacheprovider tests/literary -q
# 74 passed

pytest -p no:cacheprovider tests/unit/glossary -q
# 183 passed

pytest -p no:cacheprovider -q
# 2940 passed, 2 skipped, 10 deselected, 14 failed
```

The same 14 failures reproduce on a clean worktree at upstream `b5ed606` under
Linux/Python 3.11/PyMuPDF 2.1. They are pre-existing or environment-specific
(characterization goldens, PDF layout, a Windows path test); none is caused by
the literary layer.

### 2.3 Calibre inventory

```bash
docker compose -f docker-compose.dev.yml exec app \
  python -m src.literary.cli inventory \
  --library /library --out /app/data/calibre/targets.json --scan \
  --author McMurtry --author Hobb --author Ruocchio
```

Result: 28 records, 28 EPUBs, 7,696,672 words, 6 series. The full metadata
inventory (220 records) was also produced without scanning unrelated EPUB
content. The inventory itself remains read-only.

### 2.3.1 Calibre metadata standardization (applied 2026-11-07)

```bash
# Dry-run first; the report lists every planned change.
python scripts/literary/apply_calibre_metadata.py \
  --root literary-resources \
  --library-path "C:/Users/Bellussi/Biblioteca do calibre" \
  --out data/calibre/metadata-dryrun-report.json

# Apply with an automatic metadata.db backup.
python scripts/literary/apply_calibre_metadata.py \
  --root literary-resources \
  --library-path "C:/Users/Bellussi/Biblioteca do calibre" \
  --backup-dir data/calibre/backup \
  --out data/calibre/metadata-apply-report.json --apply
```

Result: 28 records updated through `calibredb set_metadata`, 28 executed, 0
mismatches. Backup:
`data/calibre/backup/metadata-20261107-200323.db`. The main corrections were:

- Sun Eater novels 2–7 received `The Sun Eater` and indices 2–7; the PT book 1
  title was normalized to `Império do Silêncio`.
- Farseer PT titles were replaced with the titles on the editions' title pages:
  `O Aprendiz de Assassino`, `O Assassino do Rei`, `A Fúria do Assassino`.
- Lonesome Dove PT was renamed `Pombo Solitário`, its `author_sort` changed from
  `Unknown` to `McMurtry, Larry`, and its language kept as `por`.
- The Rain Wild omnibus kept its metadata (`The Rain Wild Chronicles`, index 1)
  but remains deferred in the queue.

`data/calibre/targets.json` was regenerated after the update: 28 records, 28
EPUBs, 7,696,672 words, 6 series. The inventory reports four informational
mismatches because the internal EPUB `dc:title` still carries the old title in
the four PT files; the original EPUBs were deliberately not rewritten.

### 2.4 Resource compilation

```bash
python -m src.literary.cli resources validate --root literary-resources
# 21 files, passed

python -m src.literary.cli resources compile \
  --root literary-resources \
  --author robin-hobb --universe realm-of-the-elderlings \
  --subseries farseer --book assassins-apprentice \
  --glossary-out data/compiled/farseer1-glossary.json \
  --style-out data/compiled/farseer1-style.yaml
```

Result: 18 canonical terms, no issues, 1 forbidden term; they compile into 29
prompt entries because short forms (Fitz, Prince Verity, …) have their own
targets. Style assembled through the upstream assembler. Lonesome Dove: 20
canonical terms, 29 prompt entries, 2 forbidden. Sun Eater: 16 canonical terms,
27 prompt entries, 1 forbidden. The compiled Farseer preset also loaded through the upstream
`load_custom_instructions` (translation 2,689 chars; refinement 2,738 chars),
so it is compatible with the web UI's `Custom_Instructions/` flow.

A queue dry run added the three Liveship Traders books (local placeholder
model) and the three Tawny Man books (Gemini estimate): 6 books, 1,779,215
words, estimated cloud cost $7.54. The queue sorts by series and
`series_index`; no job was launched.

### 2.5 End-to-end EPUB translation (local, no cloud)

Fixture: `tests/fixtures/translation_sampler.epub` (1,784 words, public
domain). Model: `qwen3.5:4b` via host Ollama. Target: `Portuguese (Brazil)`.

```bash
docker compose -f docker-compose.dev.yml exec app \
  python translate.py -i tests/fixtures/translation_sampler.epub \
  -o /app/data/smoke/sampler_ptbr.epub -sl English -tl "Portuguese (Brazil)" \
  --provider ollama -m qwen3.5:4b
```

Observed:

- 10 content files, 12 chunks, 2:25 total.
- Checkpoints saved after every chunk; partial XHTML state saved/resumed.
- Placeholder validation failed on several chunks and the token-alignment
  fallback was used.
- Output EPUB is structurally valid; `dc:language` is `pt-BR`; TOC and nav
  were updated.
- **The 4B model corrupted TOC labels** (“PrefácioUma”, “CoelhoAlice”) and the
  title (“O Samplir do Tradutor”). Our validator caught the TOC errors and
  refused to pass the file.

This is the expected POC result: the infrastructure works; the small model is
not production quality; the validator does its job.

### 2.5.1 Hy-MT2 7B pilot (2026-11-07)

The same fixture was translated with the official Hy-MT2 Q4_K_M GGUF:

```bash
docker compose -f docker-compose.dev.yml exec app \
  python translate.py -i tests/fixtures/translation_sampler.epub \
  -o /app/data/smoke/sampler_hy_ptbr.epub -sl English -tl "Portuguese (Brazil)" \
  --provider ollama -m hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M
```

Observed:

- 10 content files, 12 chunks, 0 failed, 3:03 total, after the Ollama
  configuration fix (parallel 2, 8K, FA on, q8_0 KV): Hy-MT2 stayed at 100% GPU
  and about 5.0 GB VRAM during the run.
- Placeholder validation failed on 4 chunks (`ch02`, `ch04`, `ch05`, glossary)
  and the token-alignment fallback repositioned the tags. The output is
  structurally valid, but approximate tag positions remain a layout risk.
- The first validator run, before the dropcap gate existed, returned
  `passed: true` with 0 blocking issues and 1 warning (`epub.spine_extra`, the
  attribution page). The title became `Amostra do Tradutor`; TOC labels were
  preserved without concatenation. Three labels kept trailing punctuation
  (`II. ... –`, `IV. ... ,`, `V. ... ,`), a minor editorial issue.
- Adding the dropcap gate (2.10) changed the result to `passed: false` with 4
  blocking errors: `AUma` (foreword), `AAlice` (ch01), the whole word `estudos`
  inside the span (ch04), and `TOs` (ch06). EPUBCheck cannot see any of these:
  the XHTML is valid, but the text is corrupted.
- `literary repair-dropcaps` fixed all four unambiguous cases. The repaired
  output passes the structural gate with 0 blocking issues and 1 warning.
  Manual reading still found one unresolved issue in ch04: the article `Os` was
  moved into the attribution paragraph (`... 1597 Os`), leaving the body without
  its article. The deterministic gate does not catch that kind of migration;
  source-aware review does.
- EPUBCheck 5.4.0 still reports the upstream `ns0:role` attribution error plus
  the fixture UUID warning. This is the same bug as 2.8, not a Hy-MT2
  regression.
- The upstream CLI left the checkpoint row in `running` even after 12/12
  chunks. `queue sync` inferred completion from progress, moved the queue job to
  `validating`, and the EPUBCheck/dropcap failures then moved it to
  `needs_review`.

This is a better structural result than the 4B model: Hy-MT2 did not corrupt the
TOC or the title, and the dropcap repair recovered all four first words. The
remaining blockers are the upstream attribution metadata, the article migration,
and the placeholder fallback; the pilot is not publish-ready.

### 2.6 Validation

```bash
python -m src.literary.cli validate epub \
  --source tests/fixtures/translation_sampler.epub \
  --target /app/data/smoke/sampler_ptbr.epub --language pt-BR
```

Qwen3.5 4B result: `passed: false`; one blocking `epub.toc_concatenated` error
(“PrefácioUma”), plus warnings for an extra attribution document and truncated
TOC labels. This is a deliberate gate, not a false positive: the final EPUB
would have a broken navigation pane.

Hy-MT2 7B result before the dropcap gate: `passed: true`, 0 blocking issues and
one warning (`epub.spine_extra`, the optional attribution page). After the
dropcap gate was added: `passed: false`, 4 blocking `epub.dropcap_*` errors.
After `literary repair-dropcaps`: `passed: true` again, with the same warning.
The gate distinguishes a small model failure from a structurally valid file,
and the dropcap check distinguishes valid XHTML from correct text.

### 2.7 Benchmark pilot

15 excerpts, 5 per book. Models tested: TranslateGemma 12B, Qwen3 8B, Qwen3
14B, Hy-MT2 7B and Index-Translate 9B. Results and error analysis are in
`BENCHMARK.md`.

Headline findings:

- TranslateGemma 12B: fluent but critical semantic errors (“pup” → “bread”,
  male narrator → “nua”, invented fauna).
- Qwen3 8B: best installed generalist throughput/quality trade-off; correct
  “pup” and narrator gender; omitted a long clause and mistranslated regional
  terms.
- Qwen3 14B: slower, better on some long syntax, but reversed “turned away from
  me” and garbled a phrase; not a uniform improvement.
- A glossary round (`Fugue → Fuga`) fixed the concept in both Qwen models; it
  did not fix syntax or literalism.
- Hy-MT2 7B: 15/15, mean 4.5 s after the Ollama configuration fix; kept `Fuga`
  capitalization. Grammar is not flawless: the first run produced `Convenci-me`,
  the re-run produced `Convinci-me`. Stronger terminology candidate.
- Index-Translate 9B: 15/15, mean 5.2 s, no longer clearly faster; lowercased
  the glossary term and produced `Convinquei-me`. The first run's agreement
  error did not recur in the re-run. Needs PT-BR post-edit.

No tested model passes the production gate on this pilot. That is the finding,
not a failure of the POC.

### 2.8 EPUBCheck

EPUBCheck 5.4.0 was run in a Java 17 container (the host has Java 8):

```bash
docker run --rm \
  -v "$PWD/data/tools/epubcheck-5.4.0:/epubcheck:ro" \
  -v "$PWD/data/smoke:/books:ro" \
  eclipse-temurin:17-jre \
  java -jar /epubcheck/epubcheck.jar /books/sampler_ptbr.epub
```

Result: 1 error, 1 warning. The warning is the fixture's invalid UUID. The error
is `RSC-005`: the translated output adds
`<dc:contributor ... ns0:role="trl">`, which EPUB 3.4 does not allow. The
original fixture does not have this attribute. The same error was reproduced on
both the Qwen3.5 and Hy-MT2 outputs. This is an upstream EPUB conformance bug in
the attribution branch, not a literary-layer regression.
Both candidate fixes were tested with EPUBCheck and remove the error: drop the
attribute, or keep the role through a canonical
`<meta refines="#tbl-translator" property="role" scheme="marc:relators">`
element. The fix is not applied in this fork yet.

### 2.9 Source-aware selective refinement

The source-aware runner is wired to a text CLI:

```bash
python -m src.literary.cli refine \
  --source data/smoke/refine_test/source.txt \
  --draft data/smoke/refine_test/draft.txt \
  --out data/smoke/refine_test/refined.txt \
  --author robin-hobb --universe realm-of-the-elderlings \
  --subseries farseer --book assassins-apprentice \
  --model hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M \
  --temperature 0.0
```

Synthetic test: the source has `FitzChivalry Farseer`, the digit `3`, and the
glossary term `The Fool → Bobo`; the draft deliberately contains the forbidden
`Fitz Chivalry`, omits the digit, and uses `dois`. The deterministic flags found
five issues. Hy-MT2 revised the paragraph to:

> FitzChivalry Farseer cavalgou por três dias até Buckkeep. O Bobo esperava.

The guard accepted the edit (11.3% edit ratio, no number loss after the new
number-word normalization) and rejected no content. This is the key difference
from the blind upstream refine: the model saw the source and the exact flagged
issues, and the guard had the final say. EPUB-level application is still a
separate writer step.

### 2.10 Dropcap content gate and repair

The pilot exposed a content bug that a structural check cannot see: dropcap
spans were empty, contained a whole word, or kept the source letter in front of
the translated word. `validate epub` now flags:

- `epub.dropcap_empty`: `<span class="dropcap"/>` (first letter lost);
- `epub.dropcap_invalid`: a full word or placeholder inside the span;
- `epub.dropcap_letter`: the span letter is not the first letter of the
  following word (`A` + `Uma`, `T` + `Os`).

These are `ERROR` severity because they corrupt the text. On the Hy-MT2 pilot
the gate found four blocking errors that EPUBCheck did not report.

The safe repair is deterministic:

```bash
python -m src.literary.cli repair-dropcaps \
  --source data/smoke/sampler_hy_ptbr.epub \
  --out data/smoke/sampler_hy_ptbr_fixed.epub \
  --report data/smoke/repair_report.json
```

Result: four changes (foreword, ch01, ch04, ch06). The repaired EPUB passes the
structural gate with 0 blocking issues and 1 warning; Calibre reads and converts
it. It does not repair ambiguous cases, and it cannot recover a source letter
that the model dropped entirely. A manual read still found an article migration
in ch04 (`Os` moved into the attribution paragraph), which is exactly the kind
of issue the source-aware reviewer must catch.

### 2.11 Sun Eater 2 chapter pilot (real book)

The first real-book pilot used *Howling Dark* (Calibre 430), Chapter 1 “The Red
Company” (`xhtml/08_Chapter_1_The_Red_Com.xhtml`), with Hy-MT2-7B and the Sun
Eater glossary/style. The text stayed local under `data/pilots/` (gitignored).

| Metric | Result |
|---|---:|
| Source | 4,668 words, 116 paragraphs |
| Chunks | 12 |
| Total latency | 301.8 s |
| Output tokens | 8,070 |
| Paragraph alignment | 116/116 |
| Draft length ratio | 0.985 |
| Name recall | 0.966 |
| English leakage | 0.0% |
| Repetition ratio | 3.9% |

The first attempt let the model merge 116 source paragraphs into 80, which
invalidated paragraph-level refinement and metrics. A marker protocol
(`[[P001]]`, ...) fixed it: every chunk preserved its markers, with one fallback
paragraph in chunk 8 and four in the final short chunk. The final draft is
116/116 aligned.

After fixing three false-positive classes (`as` as an English stopword, compound
numbers, and regular glossary inflection), the automatic gate found **0 flags**
on this chapter. Manual reading still found a real grammar error: `dois milhas`
(milha is feminine). A targeted source-aware refinement with an explicit
`grammar.gender` issue was accepted by the guard at a 6.7% edit ratio, producing
`duas milhas` without number or glossary loss.

What this proves: the official Hy-MT2 template, Sun Eater glossary and style work
at chapter scale; the marker protocol preserves paragraph alignment; the guard
can apply a specific, source-backed repair. What it does not prove: EPUB-level
rebuild, TOC/footnote/italic preservation, chapter-to-chapter continuity or
publication quality. The draft still keeps `Lord Commandant` and `shuttles` in
English, and Book 2 has no PT reference in the library.

### 2.12 Calibre read test

```bash
ebook-meta data/smoke/sampler_hy_ptbr_fixed.epub
ebook-convert data/smoke/sampler_hy_ptbr_fixed.epub data/smoke/sampler_hy_ptbr_fixed.txt
```

`ebook-meta` reports `Amostra do Tradutor`, author `Various (public domain)`,
language `por`, and the translated description. `ebook-convert` reads the EPUB
and writes an 11.5 KB TXT without errors. This is a CLI read/convert test, not a
GUI or KOReader test; it proves Calibre's EPUB reader accepts the file, not that
the layout is visually perfect.

### 2.13 Queue UI

The SPA has a **Queue** tab that reads the persistent literary queue and exposes
the two controlled actions the queue needs from the browser:

- `GET /api/literary/queue` reads `data/literary_queue.db` in SQLite
  `mode=ro` and returns the book list, summary, latest job/progress and recent
  events. Active books are ordered first; pending books follow the stored
  priority.
- `GET /api/literary/library` lists English books from the Calibre inventory
  (`data/calibre/targets.json`) that are not queued yet.
- `POST /api/literary/queue/books` enqueues up to 100 `calibre_ids` at a time,
  skips duplicates, and maps host paths to the `/library` container mount so the
  EPUB can be hashed and read by the runner.
- `POST /api/literary/queue/books/<id>/move` moves a **pending** book up or
  down and renumbers pending priorities; non-pending entries are rejected with
  `409`.
- `PATCH /api/literary/queue/books/<id>` changes the stored `model` and
  `provider` of a **pending** book. Non-pending entries are rejected with
  `409`; the value is saved for the next run and does not alter a job already in
  progress.
- The Queue tab's **Model** cell is a native dropdown for pending rows, fed by
  the installed Ollama models from `/api/models`. Choosing a model PATCHes the
  row immediately. A `Custom...` option opens the modal for a model/provider
  combination that is not installed or not listed.
- The live queue uses SQLite's rollback journal (`journal_mode=DELETE`), not
  WAL: the app container cannot open the WAL `-shm` file on the Windows bind
  mount. The switch is applied after the active full-book run, when the wrapper
  is no longer writing.
- `src/web/static/queue.css` uses the existing design tokens (surfaces, borders,
  status colors, dark mode) instead of duplicating the palette.
- `src/web/static/js/queue/queue-manager.js` renders the table and refreshes
  every 10 s only while the tab is visible. It also filters the library picker,
  disables move buttons at the queue edges, and reports action results.
- The strings are in a new `queue` i18n namespace across all seven supported
  locales.
- The boundary is explicit: the UI can enqueue, reorder and set the model for
  pending books, but never starts, pauses or validates a translation job.

The active UI on port 5000 gets the tab after a restart. For validation I ran a
second isolated app on **`http://127.0.0.1:5001`** with a copy of the queue
database; it showed the 15 books, the active *Howling Dark* row, progress,
`translation_id`, events and 8 available inventory books. Moving *The Mad Ship*
above *Ship of Magic*, adding *Assassin's Apprentice* and saving a different
model for *Ship of Magic* worked against the copy; all three actions were then
reverted by restoring the copy from the live queue. The second instance does not
touch the real `data/jobs.db`.

Validation: **12** route tests, full suite **2,940 passed, 2 skipped, 14
pre-existing failures**.

### 2.14 PT-BR grammar layer

`src/literary/ptbr.py` adds high-confidence Brazilian Portuguese checks without
a required external service:

- verb forms seen in the pilot (`Convinci-me`, `Convinquei-me` -> `Convenci-me`);
- accents and common misspellings (`convem`, `menas`, `seje`, `derrepente`,
  `concerteza`, `atraves`);
- contractions (`de o` -> `do`, `em os` -> `nos`, `por o` -> `pelo`);
- pronoun case (`para mim fazer` -> `para eu fazer`, `entre eu e` -> `entre mim e`);
- impersonal *haver*, *existir* agreement and elapsed-time *fazer*;
- final `por quê`, repeated words (warning only, because repetition can be voice).

The checks carry exact character spans and suggestions. `flags_for_segment`
turns them into refinement issues, so a flagged paragraph reaches the
source-aware reviewer with the grammar reason attached. `check_with_languagetool`
is an optional adapter for a local LanguageTool server (`LANGUAGETOOL_URL`); the
pipeline never downloads or starts one by itself.

### 2.15 Continuity, best-of-N and run plan

- `src/literary/continuity.py` derives a character sheet from curated glossary
  metadata, keeps the previous chapter's summary and ending, and builds a compact
  continuity block (POV, characters, gender, aliases, address rules).
- `src/literary/best_of_n.py` ranks sampled candidates on glossary/name recall,
  number recall, length ratio, English leakage, repetition and high-confidence
  PT-BR errors. Case-sensitive glossary targets outrank lowercase matches.
  Ineligible candidates are reported with reasons; ties keep generation order.
- `src/literary/run_plan.py` resolves a queue row into a reproducible plan:
  model/provider, source path, resource scopes, glossary preview, style text,
  continuity block and pipeline flags. `queue plan --book-id` prints it. A
  compiled glossary path in `glossary_scope` is not mistaken for resource-tree
  coordinates.
- `translate.py` now accepts `--custom-instruction <file>` so a CLI full-book run
  can use the same curated style preset as the web UI. `docker-compose.dev.yml`
  mounts that file into the dev container; the image must be recreated for the
  mount to take effect.

### 2.16 Source-aware EPUB refinement

`src/literary/refine_epub.py` and the `refine-epub` CLI close the gap between
paragraph-aligned refinement and a real book:

- pairs source and target spine documents by `href`, then by order;
- extracts `<p>` paragraphs and compares them by index;
- skips paragraphs with inline markup instead of destroying italics/spans, and
  reports the count;
- flags only segments with deterministic issues, asks the model to revise with
  the source, glossary, style and continuity block in view;
- applies only guard-accepted revisions and writes a new EPUB atomically;
- emits a JSON report with flagged/attempted/accepted/rejected counts and
  per-document skips.

`refine-epub --dry-run` reports the flagged segments without calling the model.
The active *Howling Dark* run was started before this layer existed and is not
modified; the post-pass can run on its output after completion:

```bash
python -m src.literary.cli refine-epub \
  --source "data/uploads/cli_7e498fc1/Howling Dark - Christopher Ruocchio.epub" \
  --target "translated_files/Howling Dark (pt-BR).epub" \
  --out "translated_files/Howling Dark (pt-BR).refined.epub" \
  --author christopher-ruocchio --universe sun-eater --book howling-dark \
  --model hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M \
  --pov "First-person retrospective, male narrator." \
  --limit 30 --report data/pilots/sun-eater-2/howling-dark-refine.report.json
```

### 2.17 Expanded benchmark corpus and quantization round

The original pilot corpus had 15 excerpts from 3 books. The context corpus now
has **50 excerpts from 10 books** in the active queue: *Assassin's Apprentice*,
*Ship of Magic*, *The Mad Ship*, *Fool's Errand*, *Howling Dark*, *Demon in
White*, *Kingdoms of Death*, *Ashes of Man*, *The Lesser Devil* and *Queen Amid
Ashes*. The builder now spreads chapters and categories instead of always taking
the first paragraphs.

Quantization models downloaded and tested:

| Model | Size | Context | GPU/CPU | Excerpts | Mean latency | Length ratio | Name recall | Leakage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Hy-MT2 7B Q4_K_M | 4.6 GB | 8K | 100% GPU | 50 | 5.52 s | 1.0023 | 1.0 | 0.0% |
| Hy-MT2 7B Q6_K | 6.2 GB | 8K | 78% GPU / 22% CPU | 50 | 14.48 s | 1.0118 | 1.0 | 0.0% |
| Hy-MT2 7B Q8_0 | 8.0 GB | 4K | 67% GPU / 33% CPU | 5 | 35.69 s | 1.0021 | n/a | 0.0% |

Q4 and Q6 are indistinguishable on the deterministic quality metrics; Q6 is
2.6× slower because it does not fit the 8 GB card at 8K. Q8 is slower still.
**Q4_K_M remains the practical local choice.** The official Hy-MT2 GGUF
repository does **not** publish Q5_K_M; Q6_K is the next available step. The
benchmark runner accepts the compiled glossary shape and a YAML style preset, and
can produce an anonymized review sheet plus a separate label key
(`runner report-blind`).

**Full-book result.** *Howling Dark* completed all **1,074/1,074 chunks** with
0 failures. The deterministic EPUB validation passed with 0 blocking issues (69
warnings); EPUBCheck 5.4.0 reported 3 errors inherited from the source EPUB's
`role="doc-*"` attributes on `<body>`, which were removed; both the repaired and
refined outputs then passed with **0 errors / 0 warnings**. The source-aware
refinement compared 6,259 paragraphs, skipped 1,875 with inline markup,
flagged 180, accepted 120 and rejected 60; the refined EPUB passed validation
and EPUBCheck. The queue state is `needs_review`, not `completed`: machine output
still requires human review.

Removed as weak/duplicate: `qwen3.5:4b`, the stale
`gemini-3-flash-preview` manifest, the duplicate `qwen3:8b` tag and the duplicate
`translategemma:12b-it-q4_K_M` tag. After the pilot evidence, TranslateGemma 12B
(failed the semantic gate) and Qwen3 14B (slower and not uniformly better) were
also removed. Index-Translate 9B and Qwen3 8B remain as comparison baselines; Q8_0 was
removed after the round (no quality gain and heavy CPU offload). Q6_K stays until
a blind human comparison, if one is run.

## 3. What is not implemented

- Automatic queue-driven job launching; the queue stores the model, editorial
  scopes and upstream `translation_id`, and `queue plan` resolves them, but no
  runner launches the next pending book yet.
- The source-aware EPUB writer exists (`refine-epub`) but is not wired into the
  queue runner; the full-book style/refine path is still manual.
- Narrative memory is implemented as a continuity block, but not yet passed to
  the upstream full-book translation prompt (only the refinement prompt).
- EPUBCheck is a manual gate; it is not yet enforced inside the queue runner.
- The upstream `dc:contributor` EPUB 3.4 conformance error is fixed by #334 but
  not applied in this fork.
- The upstream dropcap corruption is reported in #333. The local gate and the
  unambiguous repair are implemented; the translation-time fix is not applied,
  and ambiguous or dropped letters still require review.
- Side-by-side review and glossary-conflict UI are not implemented; the Queue
  tab covers enqueue, reorder and model selection.
- Cloud model benchmark; no paid calls.
- KOReader/GUI read test; not run. Calibre `ebook-meta` and `ebook-convert`
  succeeded on the repaired pilot.
- The 50-excerpt corpus still has no aligned PT-BR references or blind human
  panel; `report-blind` prepares the latter.

## 4. Reproduce

```bash
# 1. Build and start
docker compose -f docker-compose.dev.yml up -d --build

# 2. Health
curl http://127.0.0.1:5000/api/health

# 3. Literary tests
docker compose -f docker-compose.dev.yml exec app \
  pytest -p no:cacheprovider tests/literary -q

# 4. Inventory (read-only)
docker compose -f docker-compose.dev.yml exec app \
  python -m src.literary.cli inventory \
  --library /library --out /app/data/calibre/targets.json --scan \
  --author McMurtry --author Hobb --author Ruocchio

# 5. Resources
docker compose -f docker-compose.dev.yml exec app \
  python -m src.literary.cli resources validate --root literary-resources

# 6. Cost
docker compose -f docker-compose.dev.yml exec app \
  python -m src.literary.cli estimate --words 300000 --all-scenarios

# 7. Benchmark dry-run
docker compose -f docker-compose.dev.yml exec app \
  python -m benchmark.literary.runner run \
  --models hy-mt2-7b --limit 1 --dry-run \
  --endpoint http://host.docker.internal:11434
```

## 5. Artifact paths

- Inventory: `data/calibre/targets.json`, `data/calibre/library_metadata.json`
  (gitignored).
- Compiled resources: `data/compiled/` (gitignored).
- Smoke output: `data/smoke/sampler_ptbr.epub` (gitignored).
- Benchmark runs: `data/benchmark/literary/runs/` (gitignored).
- Editorial samples and metrics: `data/editorial_samples/` (gitignored).
- Source: `src/literary/`, `benchmark/literary/`, `literary-resources/`,
  `tests/literary/`.
