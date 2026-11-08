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
# 69 passed

pytest -p no:cacheprovider tests/unit/glossary -q
# 183 passed

pytest -p no:cacheprovider -q
# 2868 passed, 2 skipped, 10 deselected, 14 failed
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

### 2.11 Calibre read test

```bash
ebook-meta data/smoke/sampler_hy_ptbr_fixed.epub
ebook-convert data/smoke/sampler_hy_ptbr_fixed.epub data/smoke/sampler_hy_ptbr_fixed.txt
```

`ebook-meta` reports `Amostra do Tradutor`, author `Various (public domain)`,
language `por`, and the translated description. `ebook-convert` reads the EPUB
and writes an 11.5 KB TXT without errors. This is a CLI read/convert test, not a
GUI or KOReader test; it proves Calibre's EPUB reader accepts the file, not that
the layout is visually perfect.

## 3. What is not implemented

- Automatic queue-driven job launching; the queue now stores the upstream
  `translation_id` and reconciles status/progress read-only through `queue
  sync`, but it does not launch the upstream runner yet.
- Source-aware selective refinement is implemented and tested on
  paragraph-aligned text; the upstream `refine_after` path and an EPUB-level
  writer are not wired to it yet.
- Narrative memory; only designed.
- EPUBCheck is available in a Java 17 container and was run manually, but it is
  not wired as an automatic gate in the pipeline.
- The upstream `dc:contributor` EPUB 3.4 conformance error is documented and
  two fixes were tested with EPUBCheck, but the fix is not applied in this fork
  yet.
- The upstream dropcap corruption is reported in #333. The local gate and the
  unambiguous repair are implemented; the translation-time fix is not applied,
  and ambiguous or dropped letters still require review.
- Web UI for the queue, glossary conflicts or side-by-side review.
- Cloud model benchmark; no paid calls.
- KOReader/GUI read test; not run. Calibre `ebook-meta` and `ebook-convert`
  succeeded on the repaired pilot.
- Full-book translation; explicitly not authorized.

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
  --models translategemma-12b --limit 1 --dry-run \
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
