# Proof of concept: what was actually built and tested

This document distinguishes **implemented and executed** from **planned**. No
cloud API was called, no Calibre file was modified and no large model was
downloaded.

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
# 26 passed

pytest -p no:cacheprovider tests/unit/glossary -q
# 183 passed

pytest -p no:cacheprovider -q
# 2825 passed, 2 skipped, 10 deselected, 14 failed
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
content. Calibre remained read-only.

### 2.4 Resource compilation

```bash
python -m src.literary.cli resources validate --root literary-resources
# 19 files, passed

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

### 2.6 Validation

```bash
python -m src.literary.cli validate epub \
  --source tests/fixtures/translation_sampler.epub \
  --target /app/data/smoke/sampler_ptbr.epub --language pt-BR
```

Result: `passed: false`; one blocking `epub.toc_concatenated` error
(“PrefácioUma”), plus warnings for an extra attribution document and truncated
TOC labels. This is a deliberate gate, not a false positive: the final EPUB
would have a broken navigation pane.

### 2.7 Benchmark pilot

15 excerpts, 5 per book. Models tested: TranslateGemma 12B, Qwen3 8B, Qwen3
14B. Results and error analysis are in `BENCHMARK.md`.

Headline findings:

- TranslateGemma 12B: fluent but critical semantic errors (“pup” → “bread”,
  male narrator → “nua”, invented fauna).
- Qwen3 8B: best installed throughput/quality trade-off; correct “pup” and
  narrator gender; omitted a long clause and mistranslated regional terms.
- Qwen3 14B: slower, better on some long syntax, but reversed “turned away from
  me” and garbled a phrase; not a uniform improvement.
- A glossary round (`Fugue → Fuga`) fixed the concept in both Qwen models; it
  did not fix syntax or literalism.

No tested model passes the production gate on this pilot. That is the finding,
not a failure of the POC.

## 3. What is not implemented

- Full queue integration with the upstream `translation_id`; the queue currently
  plans/tracks, it does not launch jobs.
- Source-aware selective refinement; only designed and priced.
- Narrative memory; only designed.
- EPUBCheck; the machine has Java 8 and EPUBCheck 5.x needs 11+. Structural
  validation is implemented.
- Web UI for the queue, glossary conflicts or side-by-side review.
- Cloud model benchmark; no paid calls.
- Hy-MT2 and Index-Translate tests; not installed.
- Calibre/KOReader read test; not run.
- Sun Eater metadata correction in Calibre; a dry-run plan
  (`metadata.yaml` + `scripts/literary/metadata_plan.py`) was generated, but no
  `calibredb` command was executed and `metadata.db` was not written.
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
