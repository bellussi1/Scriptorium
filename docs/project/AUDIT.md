# Audit of TranslateBooksWithLLMs 1.5.22

Repository audited: `hydropix/TranslateBooksWithLLMs`, upstream `main` at
`b5ed606` (version **1.5.22**), checked on **2026-11-07**. The local fork was
fast-forwarded from 1.5.16 to this revision before the audit. No upstream
behaviour was assumed from the README: every claim below was checked in the
source, the tests or a local run.

## 1. What the project is

A Flask application with a browser UI, a CLI and a job runner. It extracts a
document into text units, translates them through an LLM provider, reconstructs
the document and keeps a checkpoint. EPUB is the most mature path; TXT, SRT,
DOCX and text PDF have separate adapters. The benchmark is a separate package.

Main entry points:

- `translate.py` — CLI.
- `translation_api.py` — Flask server.
- `src/core/translator.py` — generic translation/refinement loop.
- `src/core/epub/translator.py` — EPUB extraction, per-XHTML orchestration,
  repackaging and metadata.
- `src/core/epub/xhtml_translator.py` — tag preservation, HTML-aware chunking,
  placeholder recovery and reconstruction.
- `src/persistence/checkpoint_manager.py` and `database.py` — jobs and resume.
- `src/api/handlers.py` — web job lifecycle, auto-prep, refine, completion.
- `benchmark/` — generic model/language benchmark.

## 2. Feature-by-feature audit

### 2.1 Glossary extraction and injection

**What works**

- The web UI and CLI support a named glossary with `source`, `target`,
  `category`, `gender`; CLI accepts JSON/CSV
  (`src/core/glossary/cli_loader.py`).
- The per-chunk filter injects only terms that occur in the chunk, sorted
  longest-first, with a frequency-aware cap
  (`src/core/glossary/filter.py:60`; cap at `:108`).
- A gendered cast block is injected into every chunk so pronouns remain
  correct even when the name is absent (`src/core/glossary/injector.py:107`).
- Target-side inflection is explained for inflected target languages
  (`src/core/glossary/injector.py:35`).
- NER extraction samples evenly spaced excerpts plus short windows around names
  found by a whole-book regex scan
  (`src/core/glossary/ner.py`; `src/core/glossary/name_scan.py`).
- Auto mode derives a throwaway glossary from the document before the first
  chunk (`src/core/auto_prep.py`).

**Limits relevant to long literary series**

- The database schema has no hierarchy, aliases, forbidden renderings, scope,
  provenance, confidence, first appearance or version. See
  `src/core/glossary/store.py:158` and
  `src/core/glossary/models.py:49`.
- The glossary is per book/name, not per author → universe → subseries → book.
  Nothing prevents book 3 terminology from leaking into book 1.
- Auto-extract reads 6,000 characters by default, at most 10 excerpts; the new
  name scan improves coverage but is still a sample, not a full-book entity
  index (`docs/GLOSSARY.md:529-586`; `src/core/auto_prep.py:41-49`).
- Auto mode has no review. A wrong identity pair is dropped, but a wrong
  translation is injected into every matching chunk (`docs/GLOSSARY.md:588`).
- Source forms are matched literally; the `|` syntax handles alternatives, but
  there is no alias model or morphological matching for English names/terms.
- The cast block is capped at 80 entries and injected into every chunk; this is
  a permanent token tax on a large ensemble. For English→PT it is less critical
  than for CJK, but it still costs.
- The whole glossary is not sent, which is good; the per-chunk filter is a
  reusable strength.

**Verdict:** reuse the filter/injector; replace the storage and selection layer
with the hierarchical resource compiler in `src/literary/resources.py` and
`src/literary/glossary.py`.

### 2.2 Style extraction and application

**What works**

- Nine dimensions, an abstraction linter, a deterministic assembler, and a
  reusable YAML preset under `Custom_Instructions/`
  (`src/core/style/extractor.py`, `lint.py`, `assembler.py`).
- The extractor explicitly forbids naming specific vocabulary, quotes and
  enumerations; the linter flags violations.
- `context` captures the narrative setting and is inserted as `## Setting`.
- Auto style derives a throwaway profile from the document
  (`src/core/auto_prep.py:249`).

**Limits**

- Style is a global file, not bound to author/universe/subseries/book/POV. The
  user must select it manually per job.
- The CLI has no `--style`/`--custom-instruction` flag; the docs say so
  explicitly (`docs/STYLE_EXTRACTION.md:5`). Only the web UI applies presets.
- The extraction sample is 10,000 characters, 6 excerpts; it characterizes
  tendencies, not a whole book.
- The lint is conservative; a plausible but bad rule can pass.
- A preset is applied identically to every chunk; it cannot switch between
  first-person Fitz, third-person Liveship and retrospective Sun Eater inside
  one job. This is why the project needs subseries/book profiles, not one
  global style.

**Verdict:** keep the schema and assembler; add the hierarchy and compile a
book-specific preset. Do not invent a second style format.

### 2.3 Refinement

**What works**

- A second pass exists for TXT, EPUB, SRT and DOCX; EPUB refinement preserves
  placeholders and repackages.
- The prompt has a glossary block and optional custom instructions.

**Critical problem**

`generate_refinement_prompt` (`src/prompts/prompts.py:626`) receives only the
draft translation. It never sees the English source. The system prompt tells the
model the input is “an amateur, literal, or awkward” translation and asks it to
“REWRITE it with perfect literary style”, prioritising natural flow over
preserving meaning. It even instructs synonym substitution to avoid lexical
repetition. This can:

- destroy deliberate repetition and motif;
- flatten a deliberately awkward or archaic voice;
- “correct” a faithful choice into a more familiar but less accurate one;
- introduce meaning drift with no source to check against.

The ACL 2026 study *What Does LLM Refinement Actually Improve?* (Tan et al.,
`2026.acl-long.268`) found that document-level MT followed by **segment-level**
refinement is the robust recipe; gains are mainly fluency, style and
terminology, with limited accuracy improvement. Monolingual refinement did not
outperform the general strategy. The upstream pass is monolingual and
whole-chunk, so it is structurally unable to deliver the accuracy repair the
project needs.

`src/core/refine/epub_refiner.py:1` also states: “Interruption stops cleanly
between chunks but does not persist partial state (no resume support in v1).”
A full-book refine can therefore lose paid work.

**Verdict:** do not use the existing refine as the quality gate. Implement a
source-aware, segment-level, selective refinement with a constrained diff and a
validator. Keep the upstream refine for non-critical polishing only, and add
resume before using it on a whole book.

### 2.4 Term fix on already translated books

**What works**

- New in 1.5.18+: a separate pass for a named wrong rendering, with literal and
  smart modes, a scan preview, a change report and a guard that forbids style
  rewriting (`src/core/term_fix/`, `docs/TERM_FIX.md`).
- EPUB is edited in place, untouched entries are copied byte-for-byte, and the
  NCX is corrected.

**Limits**

- It requires the user to know the wrong renderings; it does not compare with
  the source.
- In EPUB, a sentence is cut at inline tags; entity-encoded characters are not
  matched; OPF metadata is not edited.
- It is a repair tool, not a substitute for a source-aware review of a new
  translation.

**Verdict:** keep it for series-wide terminology repairs after the glossary is
updated.

### 2.5 Chunking and context

**What works**

- Token-based chunking with paragraph/sentence boundaries
  (`src/core/chunking/token_chunker.py`).
- EPUB uses HTML-aware blocks, not raw character slices
  (`src/core/epub/html_chunker.py`; `xhtml_translator.py:664`).
- `context_before`/`context_after` are the edge paragraph of the neighbouring
  chunks; the previous translation context is the last 25 words
  (`src/core/translator.py:415`).
- Adaptive context can grow on truncation/overflow, bounded in 1.5.22
  (`src/core/context_optimizer.py`; commit `1248ff2`).

**Limits**

- Token counting uses `cl100k_base`, not the selected model's tokenizer. Sizes
  and cost estimates are approximate for Gemini/DeepSeek/Qwen.
- Default `MAX_TOKENS_PER_CHUNK=450`, soft limit 80%. This is small for
  literary context. It keeps cost predictable but gives the model only a
  paragraph or two of context.
- Context is local (edge paragraphs + 25 words), not a chapter summary, POV
  state or narrative memory. Long-range continuity is not modelled.
- A larger context window is not automatically better; the project correctly
  treats it as a trade-off, but it does not test it.

**Verdict:** keep the chunker; add a chapter manifest and a relevance-filtered
context/memory layer. Measure whether it improves quality before paying for it.

### 2.6 Checkpoints and resume

**What works**

- `data/jobs.db` stores jobs and per-chunk rows
  (`src/persistence/database.py:72`).
- EPUB resume restores translated XHTML and per-file partial state
  (`checkpoint_manager.py:626`, `:905`; `epub/translator.py:1086`).
- Failed/untranslated chunks are tracked (`epub_unfinished_units`), and the
  completion verdict distinguishes completed/partial/error
  (`src/api/handlers.py:1013`).
- Parallel chunks are reconciled with a monotonic file pointer; there is an
  explicit retry ticket for files below the resume pointer
  (`epub/translator.py:1192-1351`).
- A resumed job can switch model/provider; the switch is logged
  (`src/api/handlers.py:694`).

**Limits**

- EPUB refinement has no resume.
- Plain-text mode still lacks a per-paragraph status index (upstream backlog
  item).
- The backend job store is per file; there is no saga-level queue.
- A completed job's checkpoint rows are pruned, keeping only the output; a
  later `term-fix`/re-review can use the output but not the original chunks
  unless the job is still resumable.

**Verdict:** reuse the chunk/XHTML checkpoint design; add a separate persistent
book queue that references the upstream `translation_id` and chapter hashes.

### 2.7 Parallel translation

**What works**

- Cloud providers can run `PARALLEL_TRANSLATIONS` chunks concurrently;
  `resolve_parallel_workers` forces local providers back to one
  (`src/config.py:168`).
- Per-job cost tracking is context-local, so concurrent jobs do not mix totals
  (`src/core/llm/cost_tracker.py`).

**Limits**

- Local Ollama is serialized; the UI field is ignored for local models.
- Parallel chunks increase peak rate-limit risk; the project auto-pauses on 429
  but this is a cost/latency trade-off, not free throughput.
- The queue is browser-local, so parallel jobs from multiple tabs are not a
  supported scheduler.

**Verdict:** keep the cloud parallel path; the literary queue should schedule
one book at a time by default, with an explicit concurrency cap.

### 2.8 EPUB preservation

**What works**

- Tags are replaced by placeholders, validated and restored
  (`xhtml_translator.py:95-252`; `placeholder_validator.py`).
- A two-phase token-alignment fallback exists when placeholders cannot be
  restored (`epub/token_alignment_fallback.py`).
- NCX and EPUB3 nav labels are updated; XHTML `lang` is set; RTL/LTR is
  handled; OPF metadata can be localized; the ZIP is rebuilt with safe
  extraction (`src/utils/security.py`).
- Bilingual mode interleaves original and translation.

**Limits**

- No EPUBCheck gate; the structural checks are internal.
- Token-alignment fallback can produce approximate tag positions and, in our
  smoke test, corrupted TOC labels (“PrefácioUma”, “CoelhoAlice”). The fallback
  is a repair path, not a quality guarantee.
- The translated title can be wrong (“O Samplir do Tradutor” in the smoke test)
  and there is no metadata sanity check.
- EPUB refinement rewrites whole XHTML files and has no resume.
- The upstream pipeline adds an attribution page by default; this changes the
  spine count. It is intentional but must be accounted for by validators.
- No end-to-end Calibre/KOReader test was run in this audit.

**Verdict:** reuse the tag/placeholder architecture; add our structural
validator, TOC-label checks, EPUBCheck (after installing a modern JDK) and a
metadata sanity pass.

### 2.9 Queues and job management

**What works**

- The backend has resumable jobs, pause/interrupt, partial output, failure
  isolation and a completion verdict.
- The UI has a batch controller and resume cards.

**Limits**

- The batch queue is stored in browser `localStorage`
  (`src/web/static/js/translation/batch-controller.js:154`); closing the
  browser loses the queue. The README says so.
- No saga/book-level state (`pending → preparing → translating → reviewing →
  validating → completed`).
- No cost preflight per book/saga; the UI has a per-job estimator, not a
  budget gate.
- No persistent approval/review state for chapters.

**Verdict:** add `src/literary/queue.py` as the system of record; let the
browser UI read it rather than own it.

### 2.10 Providers and pricing

**What works**

- Ollama, OpenAI-compatible, OpenAI, Gemini, OpenRouter, Mistral, DeepSeek,
  Poe and NVIDIA NIM.
- Per-job API keys, key pools, 429 handling, automatic pause/resume, cost
  tracking for OpenRouter (exact `usage.cost`) and a fallback rate table.
- Endpoint allowlist and SSRF/path protections.

**Limits**

- `src/core/pricing/pricing_data.py` says “Last updated: 2026-05-09”; some
  model IDs are stale (e.g. Gemini 2.0/2.5, DeepSeek V4 names). The UI allows
  overrides, but defaults can mislead.
- The estimator does not price glossary/style blocks, context growth, auto-prep,
  validation, retries correctly, or the refine pass’s different input shape
  (`src/core/pricing/estimator.py:49`).
- Key rotation exists (`docs/API_KEY_ROTATION.md`). It is useful for legitimate
  multiple accounts, but it must not be used to evade provider limits; this
  project will not configure it for that purpose.
- DeepSeek privacy is a first-order issue: the official API policy allows
  training on user data by default and has no published ZDR tier. Do not send
  copyrighted books there without explicit informed consent.
- Gemini paid tier retains logs for up to 55 days by default; free tier content
  may be used to improve products.

**Verdict:** keep the provider layer; replace the default pricing table with a
dated, auditable registry and use the literary cost model for decisions.

## 3. Bugs and risks that affect this project

| Risk | Evidence | Impact | Mitigation |
|---|---|---|---|
| Blind refine rewrites without source | `src/prompts/prompts.py:626-820` | Meaning drift, flattened voice, lost repetition | Source-aware segment refinement; do not run blind full-book refine |
| TOC corruption under fallback | Local smoke test with `qwen3.5:4b`; target TOC “PrefácioUma”, “CoelhoAlice” | Broken navigation in final EPUB | TOC-label validator; retry with a stronger model; never accept fallback silently |
| Glossary schema insufficient | `store.py:158`, `models.py:49` | Cross-book inconsistency, no aliases/forbidden | Hierarchical YAML + compiler |
| NER sampling misses late terms | `docs/GLOSSARY.md:529-586`; `auto_prep.py:41` | Character/term drift in later chapters | Whole-book pre-scan + human review + glossary growth |
| Auto mode unreviewed | `docs/GLOSSARY.md:588` | A wrong term propagates to every chunk | Use reviewed glossary for production; auto only for drafts |
| Browser-only queue | `batch-controller.js:154` | Lost queue, no saga planning | Backend SQLite queue |
| Refine no resume | `refine/epub_refiner.py:1-5` | Paid work lost on interruption | Add checkpointing before use |
| Cost estimate optimistic | `pricing/estimator.py` | Budget surprises | New cost model; actual usage logging; budget cap |
| No EPUBCheck | No integration found | Structurally invalid EPUB can ship | Install JDK 17 + EPUBCheck; gate |
| Prompt injection in book text | No explicit defense in prompts | A malicious EPUB can try to alter instructions | Treat text as data; delimit; no tools; output validation; human review |
| Calibre metadata is inconsistent | Sun Eater series, Lonesome Dove author_sort | Wrong queue order/identity | Resource `series.yaml`; corrected output metadata; no DB writes |
| Upstream bind is 0.0.0.0 | `translation_api.py` defaults | LAN exposure | Dev Compose binds `127.0.0.1`; token auth remains |

## 4. Test coverage

The upstream suite is substantial. In the dev container:

```
2984 passed, 2 skipped, 10 deselected, 14 failed
```

The same 14 failures reproduce on a clean worktree at upstream `b5ed606`
under Linux/Python 3.11/PyMuPDF 2.1. They are **pre-existing/environmental**,
not caused by this project:

- 8 characterization golden mismatches: progress sequence/progress key changes
  and CRLF vs LF in text outputs;
- 5 PDF layout/header detection failures tied to the installed PyMuPDF 2.1;
- 1 path-validator backslash test that is platform-specific.

New tests added by this project:

- 74 tests under `tests/literary/` (inventory, EPUB, hierarchy, glossary
  selection, forbidden rendering, queue, cost, validation).
- All 183 upstream glossary tests pass, including the byte-identical
  no-forbidden block regression.

Existing test families relevant to this project:

- `tests/unit/epub/` — tag preservation, placeholders, issue #207 content loss,
  issue #288 loose text, metadata translator, NCX labels.
- `tests/test_epub_retry_failed_chunks.py` — failure recovery.
- `tests/test_epub_interruption_integration.py` — interruption/resume.
- `tests/test_checkpoint_manager_xhtml.py` — per-file state.
- `tests/unit/test_parallel_translation.py`, `test_token_alignment_fallback.py`.
- `tests/unit/term_fix/` — rules, matcher, guard, formats.
- `tests/unit/style/` — parser, assembler, lint, endpoints.
- `benchmark/` — generic model/language benchmark, not a literary PT-BR
  benchmark.

Coverage gaps for our case: no saga-level queue, no EPUBCheck gate, no
source-aware refine tests, no TOC-label validation, no PT-BR literary corpus,
no continuity/memory tests, no cost preflight integration.

## 5. Reuse vs change

| Area | Decision |
|---|---|
| EPUB extraction, tags, placeholders, reconstruction | **Reuse unchanged**; add validator/gate |
| Checkpoints and resume | **Reuse**; add book-level queue |
| Provider layer | **Reuse**; update model/pricing registry |
| Per-chunk glossary filter and cast block | **Reuse**; feed it compiled hierarchical terms |
| Glossary storage | **Replace/augment** with YAML resources + compiler |
| Style schema/assembler | **Reuse**; add hierarchy and CLI/API wiring |
| Refine | **Do not use as-is**; build source-aware selective refinement |
| Term fix | **Reuse** for series-wide repairs |
| Benchmark | **Reuse provider/metric ideas**; add `benchmark/literary/` |
| Docker | **Replace the dev path** with a source build; keep the published image as an option |
| Web UI | **Keep**; add queue/resource views only if the backend exists |
