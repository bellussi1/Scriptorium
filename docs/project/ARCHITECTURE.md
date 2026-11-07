# Architecture

## 1. Decision: fork with additive modules (option B)

Three options were compared:

| Option | Verdict |
|---|---|
| A. Use upstream almost unchanged | Rejected. The EPUB/checkpoint/provider core is strong, but the glossary model, style binding, queue and blind refinement are insufficient for long literary series. |
| B. Fork with incremental improvements | **Chosen.** Keep the upstream translation/EPUB core; add a separate literary layer; patch upstream only where the integration boundary is small and testable. |
| C. Reuse parts and rewrite the architecture | Rejected for now. It would duplicate a mature EPUB/placeholder/checkpoint implementation and make upstream security/format fixes harder to absorb. Revisit only if the fork becomes unmergeable. |

The fork is intentionally shallow:

- New code lives in `src/literary/`, `benchmark/literary/`,
  `literary-resources/`, `tests/literary/` and `docs/project/`.
- Upstream patches are limited to:
  - `src/core/glossary/cli_loader.py` — read `forbidden` from JSON/CSV.
  - `src/core/glossary/injector.py` — render forbidden renderings, while
    preserving byte-identical output when none are present.
  - A future optional `--style` CLI flag (not implemented in this POC).
- Everything else calls the existing pipeline.

Upstream sync procedure:

1. `git fetch upstream && git merge --ff-only upstream/main`.
2. Re-run `pytest`; confirm the same pre-existing failures, if any.
3. Re-run the literary tests and the smoke translation.
4. If an upstream change touches a patched file, keep the patch minimal and
   add a regression test before merging.

## 2. Target pipeline

```text
Calibre library (read-only)
        |
        v
Inventory: books, authors, series, languages, EPUB metadata, word counts
        |
        v
Book plan: author -> universe -> subseries -> book; queue order; cost preview
        |
        v
Resource compile: glossary + characters + worldbuilding + style
        |
        v
EPUB prep: spine manifest, chapter boundaries, source hashes, TOC map
        |
        v
Persistent queue: pending -> preparing -> translating -> reviewing
        |                                      -> validating -> completed
        v
Upstream translation core
  - HTML-aware segmentation
  - per-chunk glossary selection + style + measured context
  - provider call with retry/backoff/budget guard
  - checkpoint after every unit
        |
        v
Deterministic validation (blocking issues -> needs_review, never auto-rewrite)
        |
        v
Selective source-aware refinement (only flagged units; constrained diff)
        |
        v
Continuity check: names, terms, POV, gender, chapter seams
        |
        v
EPUB reconstruction + metadata (pt-BR) + EPUBCheck/structural gate
        |
        v
Human review / approval -> translations library
```

The upstream core is kept for the middle of the pipeline. The new layer owns
planning, editorial resources, queue, cost, validation and the quality gate.

## 3. Components

| Component | File | Responsibility |
|---|---|---|
| Calibre inventory | `src/literary/calibre.py` | Read-only SQLite query, EPUB scan, series/duplicate detection |
| EPUB utilities | `src/literary/epub.py` | Metadata/TOC/text extraction, structural validation, safe metadata rewrite |
| Resource hierarchy | `src/literary/resources.py` | Load/merge/validate YAML, compile glossary + style for a book |
| Glossary selection | `src/literary/glossary.py` | Aliases, forbidden renderings, first-appearance filtering, token budget |
| Persistent queue | `src/literary/queue.py` | Book/chapter states, idempotency, checkpoints, events |
| Cost model | `src/literary/cost.py` | Dated pricing registry, measured token ratios, scenarios A–E |
| Validation | `src/literary/validation.py` | Pair-level and EPUB-level deterministic checks |
| CLI | `src/literary/cli.py` | Inventory, resources, queue, estimate, validate, metadata |
| Benchmark | `benchmark/literary/` | Local corpus, model-specific prompts, metrics, report |
| Dev environment | `docker-compose.dev.yml`, `deployment/Dockerfile.dev` | Source build, host Ollama, read-only Calibre, healthcheck |

## 4. Glossary hierarchy

### 4.1 Layout

```text
literary-resources/
  global/pt-br-conventions.yaml
  <author>/<universe>/
    series.yaml
    glossary.yaml
    characters.yaml
    worldbuilding.yaml
    style.yaml
    <subseries>/
      glossary.yaml
      style.yaml
      <book>/
        glossary.yaml
        style.yaml
```

Only create files that carry information. The README in
`literary-resources/` documents the fields.

### 4.2 Precedence and merge rules

`global < author < universe < subseries < book < chapter`.

- A higher-scope term overrides `target`, `category`, `policy`, `gender`,
  `notes`, `confidence` and `first_appearance`.
- `aliases` and `forbidden` are unioned, never dropped.
- A higher-scope style profile overrides scalar fields (`mode`, `context`);
  rules replace the same dimension; `translation`/`refinement` prose overrides
  the assembled text if explicitly provided.
- `series.yaml` is the source of truth for order and PT titles. It is not
  duplicated in the database.

### 4.3 Term model

```yaml
source: "FitzChivalry Farseer"
target: "FitzChivalry Farseer"
category: character
policy: keep
aliases: [Fitz, FitzChivalry]
forbidden: ["Fitz Chivalry", "Fitz, o Farseer"]
gender: male
number: singular
notes: "..."
source_reference: "Official PT-BR edition, Calibre 94"
confidence: confirmed
first_appearance: assassins-apprentice
approved: true
```

`policy` values: `translate`, `keep`, `adapt`, `transliterate`, `contextual`.
`confidence` values: `confirmed`, `reviewed`, `provisional`.
`first_appearance` excludes terms introduced in later volumes from earlier
books; this is spoiler and continuity control, not just a dictionary.

### 4.4 Per-chunk selection

The compiler emits a full glossary JSON for auditability, but the request does
**not** receive the whole glossary.

`select_terms(chunk, compiled)`:

1. matches the canonical source and every alias with word boundaries (Latin)
   or substring (CJK);
2. counts occurrences;
3. ranks by frequency, length, approval and confidence;
4. keeps entries until a **token budget** (default 900 tokens, 50 entries);
5. renders a compact block with category/gender/forbidden hints.

The cast block is the only exception: gendered entries are injected in every
chunk so a pronoun-only passage does not lose the character's gender. It is
capped (80 entries) and should be filtered by book order.

### 4.5 What the glossary does not do

- It does not guess terminology from fan translations.
- It does not send the whole dictionary to the model.
- It does not resolve every ambiguity; `notes` and `confidence` exist so a
  human can review the hard cases.
- It does not replace source-aware validation; a wrong target still needs to be
  caught.

## 5. Style profiles

The upstream schema is kept:

```yaml
description: ...
mode: source
context: ...
rules:
  - dimension: narrative_voice
    instruction: ...
translation: |   # optional; assembled if absent
refinement: |    # optional; assembled if absent
```

The hierarchy adds:

- a universe base (`realm-of-the-elderlings/style.yaml`);
- subseries overrides (`farseer/style.yaml`, `liveship-traders/style.yaml`, …);
- optional book overrides;
- `evidence` and `notes` as metadata, ignored by the translation loader.

Rules describe **tendencies**, never a fixed vocabulary. The compiler uses the
upstream `assemble_instructions` so the preview and the saved preset cannot
drift. To install a compiled profile for the web UI:

```bash
python -m src.literary.cli resources compile \
  --root literary-resources \
  --author robin-hobb --universe realm-of-the-elderlings \
  --subseries farseer --book assassins-apprentice \
  --style-out Custom_Instructions/farseer.yaml
```

The preset then appears in the Styles tab. A future `--style` CLI flag will call
the same loader; the upstream CLI does not have it yet.

Why this is not one global style: Farseer is first-person memoir, Liveship is
third-person multi-POV, Rain Wild is a young ensemble, Sun Eater is a
retrospective historian. Applying one preset to all of them would flatten the
differences the user explicitly wants to preserve.

## 6. Narrative memory (proposed, not implemented)

The system must not pretend the model remembers previous requests. A structured
memory is useful only if it measurably improves continuity. Proposed schema:

```yaml
book: howling-dark
chapter: 12
events:
  - id: ...
    summary: ...
    characters: [Hadrian, ...]
    spoiler_after: chapter-12
relationships:
  - pair: [Hadrian, Valka]
    state: ...
world_state:
  location: ...
  time: ...
voice:
  pov: first-person
  register: retrospective
ambiguities:
  - source: "..."
    decision: pending
```

Rules:

- Store editorial facts, not raw book text.
- Tag every item with `first_relevant`/`spoiler_after` so future information is
  never injected into earlier chapters.
- Retrieve by character/place/term overlap, not by dumping the whole memory.
- Version it; a wrong memory must be correctable and traceable.
- Measure the quality delta on a chapter seam before adding it to production.
- Do not implement it just because it sounds sophisticated. The ACL 2026
  refinement study and our pilot suggest that source visibility and glossary
  control matter more than a large memory block; test that first.

## 7. Refinement design

The existing blind rewrite is replaced (for production quality) by:

1. **Trigger:** deterministic validator flags a unit, or a chapter-seam check
   finds a continuity issue.
2. **Input:** source segment + draft translation + glossary + style + only the
   relevant context.
3. **Task:** locate and fix specific problems; do not rewrite for taste.
4. **Guard:**
   - placeholders/tags identical;
   - numbers/dates preserved;
   - no new named entity;
   - no omission/invention;
   - edit distance bounded (e.g. ≤35% of tokens) unless the unit is marked
     “retranslate”;
   - forbidden renderings absent;
   - source-aware semantic check (LLM judge or human) for flagged units.
5. **Fallback:** keep the draft, mark `needs_review`, never silently replace.
6. **Granularity:** segment-level (paragraph or smaller), not whole book.
7. **Cost:** only flagged units, not every chunk. The cost model prices this
   separately.

The ACL 2026 study supports document-level context plus segment-level
refinement; it also warns that refinement gains are mostly fluency/style, with
limited accuracy improvement. That is exactly why the reviewer must see the
source and why a validator, not the refiner, decides what is “fixed”.

**Implementation status (2026-11-07).** `src/literary/refine_runner.py` implements
the segment selector, the Ollama client and the auditable report; the
`literary refine` CLI applies accepted replacements to paragraph-aligned text.
The guard now normalizes number words (`3` and `três` are equivalent), after a
real false positive on a Hy-MT2 refinement. EPUB-level application and the
upstream `refine_after` hook are still pending.

## 8. Persistent queue

`src/literary/queue.py` uses a separate SQLite database
(`data/literary_queue.db`) with:

- `books` — identity, series, source hash, config hash, status, priority,
  model/provider, estimated/actual cost.
- `jobs` — a run of a book, current chapter, total chapters, checkpoint JSON,
  error.
- `chapters` — per-chapter status, source/translated hash, token counts, cost,
  validation JSON.
- `events` — append-only audit log without book text.

States:

```text
pending -> preparing -> translating -> reviewing -> validating -> completed
                |             |             |             |
                +-------------+-------------+-------------+-> paused
                +-------------+-------------+-------------+-> failed
                +-------------+-------------+-------------+-> needs_review
```

Properties:

- **Idempotent:** `(calibre_id, source_hash, config_hash)` is unique.
- **Resumable:** a server restart turns in-progress work into `paused`.
- **Chapter-level:** a failed chapter does not invalidate the book.
- **No book text in the queue:** only paths and hashes, so logs and DB dumps are
  safer.
- **Upstream link:** a job stores the upstream `translation_id`. `queue attach`
  links a job and `queue sync` reconciles status and chunk progress read-only
  from `data/jobs.db` (running → translating, paused/interrupted → paused,
  error → failed, partial → needs_review, completed → validating). Because the
  CLI can exit without flipping the row from `running`, sync infers
  `completed`/`partial` when `completed_chunks >= total_chunks`. Chunk-to-
  chapter mapping and automatic job launching are still pending; the queue
  records the upstream chunk counts in `checkpoint_json`.
- **Saga order:** `series.yaml` supplies order; `priority` allows manual
  override.
- **Budget:** estimated cost is stored before the run; actual cost is appended
  per chapter; a budget gate blocks the next chapter when the cap is reached.

The browser queue is not the system of record. The UI should read this store.

## 9. Validation and quality gates

Two layers:

### Deterministic (blocking or review)

- empty/omitted paragraphs;
- placeholder/tag multiset;
- numbers/dates;
- untranslated English leakage;
- glossary target missing / forbidden rendering present;
- TOC label concatenation, truncation or length anomaly;
- dropcap span empty, over-long or not starting the following word; a
  deterministic repair handles the unambiguous cases;
- repeated n-grams not present in the source;
- language metadata (`pt-BR`);
- EPUB ZIP/OPF/spine/manifest/internal links/XML;
- spine count drop;
- chapter title/metadata sanity.

### Probabilistic (review, never auto-rewrite)

- source-aware LLM judge with the six-dimension rubric;
- blind A/B comparison between candidates;
- human spot-check of flagged units.

Important errors (omission, inversion, invention, wrong language, broken
structure) are **gates**: a high average cannot save a unit that fails a gate.
The rubric is in `../LITERARY_RUBRIC.md`.

## 10. EPUB preservation

Reuse the upstream tag/placeholder architecture. Add:

- `validate_epub_structure` before and after;
- TOC label validation (the smoke test proved this is necessary);
- dropcap validation and a conservative repair pass (the Hy-MT2 pilot proved
  both are necessary);
- metadata `dc:language = pt-BR` and series/index correction on the output;
- EPUBcheck once a modern JDK is installed (the machine currently has Java 8;
  EPUBCheck 5.x needs 11+);
- a reading test in Calibre and KOReader before marking a book complete;
- no change to the source EPUB, ever.

Known upstream caveat: the token-alignment fallback can rewrite tag positions
approximately. Treat fallback as `needs_review`, not as success.

## 10.1 User interface

Do not rebuild the UI. The existing interface already has file upload, batch
queue, progress, glossary CRUD, style CRUD, resume cards and a cost estimator.
The missing views are all backend-driven:

- a book/saga list fed by `data/literary_queue.db`;
- chapter progress and checkpoint state per book;
- cost preview and budget status per book/saga;
- glossary conflicts and unapproved/provisional terms;
- side-by-side source/draft/validated text for flagged units;
- a validation report with blocking issues and a chapter approval action.

Reuse the existing components, i18n markers and provider/model selectors. The
UI must not become the source of truth for the queue; it reads and mutates the
backend store through the API. No new dashboard framework is needed.

## 11. Security and privacy

- The app binds to `127.0.0.1` in the dev Compose; the upstream default is
  `0.0.0.0`.
- Per-session API token auth remains enabled; CORS is same-origin.
- Calibre is mounted read-only; output is a separate directory.
- The container runs as UID 1000, drops capabilities, uses
  `no-new-privileges`, a read-only root filesystem and tmpfs `/tmp`.
- Secrets stay in `.env`/environment, never in resources, logs or prompts.
- Book text is **untrusted data**. The prompt must delimit it, never treat it
  as system instructions, and never expose tools to the translation call.
  This reduces prompt injection; it does not make it impossible. Validation and
  human review remain necessary.
- The upstream prompt uses `<input>`/`<translate>` delimiters. A malicious
  EPUB could include those literal tags and try to close the delimiter. Add a
  deterministic escape/replace step for delimiter tokens before prompting;
  this is a small, testable patch, not a complete security boundary.
- No DRM removal, no credential rotation to bypass limits, no sending
  copyrighted books to a provider whose policy allows training without explicit
  informed consent.
- DeepSeek is the highest privacy risk among the required candidates; Gemini
  paid, OpenAI and Anthropic have clearer no-training defaults. OpenRouter
  requires ZDR/data-collection enforcement.

## 12. Licensing

The upstream is **AGPL-3.0**. This fork remains AGPL-3.0. If the modified
application is distributed or offered as a network service, the corresponding
source must be made available under the AGPL. Personal use does not trigger the
network-service obligation, but the licence and notices must be preserved.
Do not copy code from a non-AGPL-compatible project into this repository
without checking the licence.

## 13. Directory layout

```text
src/literary/                 new literary layer
benchmark/literary/           local literary benchmark
literary-resources/           versioned editorial resources
tests/literary/               new unit tests
docs/project/                 this documentation
docs/LITERARY_RUBRIC.md       evaluation rubric
docker-compose.dev.yml        source-build dev environment
deployment/Dockerfile.dev     dev image
data/                         runtime, gitignored
translated_files/             output, gitignored
```

## 14. What not to build

- A second EPUB parser or tag-preservation engine.
- A second provider abstraction.
- A web dashboard before the backend queue exists.
- A narrative-memory database before a measured quality gain.
- A full-book refine that rewrites every chunk.
- A “translate the whole library” button.
