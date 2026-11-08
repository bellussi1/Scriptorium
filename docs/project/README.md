# Literary translation project — diagnosis, architecture and proof of concept

Status: **Phases 1–3 complete. Phase 4 benchmark in progress; Phase 5 editorial
resources and Calibre metadata applied; Phase 6 pilot done on a public-domain
fixture and on one real chapter (*Howling Dark* Chapter 1).** The installed
generalists plus Hy-MT2-7B and Index-Translate-9B were tested locally on
2026-11-07. No paid cloud call was made and no full book was translated. No
model passes the production gate without editorial review.

Environment: Ollama is tuned for the 8 GB card; the Lote A/B/C cleanup is
applied (C: ~301 GB free, active container preserved). Docker VHDX compaction
is pending a maintenance window; see [ENVIRONMENT.md](ENVIRONMENT.md).

This directory is the entry point. The repository code remains the upstream
TranslateBooksWithLLMs application; the new layer is additive and lives under
`src/literary/` and `benchmark/literary/`.

## Read in this order

| Document | What it answers |
|---|---|
| [AUDIT.md](AUDIT.md) | What the upstream project actually does, where it is strong, where it breaks for long literary series, and which tests cover it. |
| [ENVIRONMENT.md](ENVIRONMENT.md) | Hardware, Docker/WSL2, GPU, Ollama, Python, Calibre library, series found, gaps and metadata problems. |
| [MODEL_RESEARCH.md](MODEL_RESEARCH.md) | Local and cloud model candidates, context limits, licences, prices checked on 2026-11-07, privacy, and a provisional recommendation. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Fork strategy, components, data flow, glossary hierarchy, style profiles, queue, validation, refinement and security. |
| [COST_MODEL.md](COST_MODEL.md) | Measured token ratios, scenarios A–E, per-book and per-saga estimates, assumptions and uncertainty. |
| [BENCHMARK.md](BENCHMARK.md) | Literary benchmark design, local corpus, rubric, pilot results and next experiments. |
| [EDITORIAL_PROFILES.md](EDITORIAL_PROFILES.md) | Evidence-based style profiles for Lonesome Dove, Realm of the Elderlings and Sun Eater. |
| [LITERARY_RUBRIC.md](../LITERARY_RUBRIC.md) | Six-dimension evaluation rubric with blocking error gates. |
| [ROADMAP.md](ROADMAP.md) | Prioritized tasks, dependencies, acceptance criteria and required approvals. |
| [DECISIONS.md](DECISIONS.md) | Architecture decision records (ADRs) behind the choices. |
| [POC.md](POC.md) | What was actually built and tested, with commands and observed results. |

## Executive summary

### What the upstream project already solves

- EPUB, TXT, SRT, DOCX and text-PDF translation; EPUB structure, tags, TOC,
  metadata and inline formatting are handled seriously.
- Checkpoints and resume at file/chunk level for EPUB and plain text.
- Per-chunk glossary injection with a frequency-aware cap, gendered cast block,
  NER extraction and a whole-book name scan.
- Style extraction with nine dimensions, an abstraction linter and an assembler
  that turns rules into translation and refinement prompts.
- A term-fix pass for already translated books, with a deterministic guard.
- A benchmark harness, provider abstraction, cost tracking and per-job API key
  handling.

### What does not fit long literary series

1. **Refinement is blind.** `generate_refinement_prompt` never sees the source
   text and explicitly tells the model to rewrite the draft as an “amateur,
   literal, or awkward” text. It cannot repair accuracy and can destroy
   deliberate repetition, ambiguity and voice. This is the most important
   quality risk in the repo.
2. **Glossary is per book.** The store has only `source`, `target`, `category`,
   `gender`. There is no hierarchy, aliases, forbidden renderings, scope,
   first appearance, provenance or cross-book versioning.
3. **NER sees ~6,000 characters** (targeted excerpts up to 5M characters, but
   the prompt budget is still tiny). Terms that appear only late are missed;
   Auto mode has no human review.
4. **Style presets are global files**, not bound to author → universe →
   subseries → book → POV. The CLI has no style flag; only the web UI selects a
   preset.
5. **The queue is browser-local.** The backend has resumable jobs, but the
   batch queue lives in `localStorage`; there is no saga-level persistent queue.
6. **EPUB validation is structural but not EPUBCheck.** The pipeline preserves
   a lot, but there is no final EPUBCheck gate and no TOC-label validator. In
   our smoke test, a small model corrupted TOC labels via the token-alignment
   fallback.
7. **Cost estimation is optimistic.** It does not price glossary/style blocks,
   context growth, retries, auto-prep, validation calls or the refine pass
   properly; it also uses an approximate tokenizer.

### What we added

- Read-only Calibre inventory with series detection, duplicates, EPUB metadata
  and word counts.
- Hierarchical YAML editorial resources with merge precedence, aliases,
  forbidden renderings, first-appearance filtering and compiled prompt assets.
- Contextual glossary selection with a token budget.
- Persistent SQLite book/chapter queue with idempotency, explicit states, a
  read-only `translation_id` sync with the upstream checkpoint database, and a
  read-only Queue tab in the web UI.
- Source-aware selective refinement for paragraph-aligned text, with an
  injected model call and a deterministic guard. EPUB writing is still separate.
- Cost model calibrated on the user's EPUBs.
- Deterministic translation and EPUB validators, including TOC-label and
  dropcap content checks.
- A deterministic dropcap repair for the unambiguous corruption patterns.
- Forbidden-rendering support in the upstream glossary prompt path.
- A literary benchmark harness with model-specific prompts and deterministic
  metrics.
- A real chapter pilot (*Howling Dark* Chapter 1) with 116/116 paragraph
  alignment, Sun Eater glossary/style and a targeted source-aware repair.
- A development Docker Compose that builds the local source, binds Calibre
  read-only and reaches host Ollama.

### Provisional decisions (evidence, not final selection)

- **Architecture:** fork with additive modules and minimal upstream patches
  (option B), not a rewrite and not an untouched upstream.
- **Local primary candidate:** **Hy-MT2-7B** is the stronger terminology
  candidate after the 2026-11-07 round: it kept glossary capitalization and
  preserved long syntax. Its grammar is not flawless: the re-run produced
  `Convinci-me` instead of `Convenci-me`. **Index-Translate-9B** is similarly
  fluent but produced `Convinquei-me` and ignores glossary case; use it as a
  draft engine with PT-BR post-edit. After the Ollama configuration fix both
  run at 4.5–5.2 s per 15-excerpt round, with 3-run medians of 49.1 and
  43.5 tok/s; Index is no longer clearly faster. Neither passes the production
  gate yet. Among generalists, **Qwen3 8B** is the best throughput/quality
  trade-off; **Qwen3 14B** is somewhat better on long syntax but much slower
  and still error-prone. **TranslateGemma 12B** is fluent but its ~2K-token
  regime, fixed prompt and observed hallucinations make it unsuitable as the
  primary engine for full novels.
- **Cloud provisional candidate:** **Gemini 3.8 Flash** for quality, with
  **DeepSeek V4.1 Flash** as the cost option only after an explicit privacy
  decision. Both need PT-BR literary tests before commitment.
- **Refinement:** source-aware, segment-level, selective. Do not run the
  existing blind full-book refine.
- **Queue:** backend SQLite, not browser storage.
- **Metadata:** Calibre metadata was standardized on 2026-11-07 through the
  official `calibredb` flow, with backup and a before/after report. Direct SQL
  writes to `metadata.db` remain forbidden.

### Non-negotiable safety rules

- Original EPUBs stay unmodified; Calibre metadata changes require explicit
  authorization, a backup and the official `calibredb` flow.
- No cloud call, large model download or full-book translation without explicit
  approval and a budget.
- No DRM circumvention, no credential rotation to evade provider limits.
- Book text is untrusted data. It must never be able to change system
  instructions or trigger tools.

### Upstream contribution

- Issue: [hydropix/TranslateBooksWithLLMs#331](https://github.com/hydropix/TranslateBooksWithLLMs/issues/331)
  is the umbrella for series-aware resources, a persistent queue, a validation
  gate and selective refinement. It now has the current evidence, acceptance
  criteria and a ready-vs-design split.
- Issue: [hydropix/TranslateBooksWithLLMs#332](https://github.com/hydropix/TranslateBooksWithLLMs/issues/332)
  reports the attribution metadata error caught by EPUBCheck 5.4.0.
- Issue: [hydropix/TranslateBooksWithLLMs#333](https://github.com/hydropix/TranslateBooksWithLLMs/issues/333)
  reports the dropcap content corruption (lost or duplicated first letters)
  found in the end-to-end pilot.
- Open PRs:
  - [PR #334](https://github.com/hydropix/TranslateBooksWithLLMs/pull/334) —
    EPUB attribution fix, 10 targeted tests, full branch suite 2,801 passed,
    EPUBCheck evidence;
  - [PR #335](https://github.com/hydropix/TranslateBooksWithLLMs/pull/335) —
    glossary `forbidden` support, 3 targeted tests, full branch suite 2,802
    passed.
  The larger slices wait for maintainer feedback before a PR.
