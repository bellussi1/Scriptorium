# Architecture decision records

Status: accepted unless marked proposed. Dates are 2026-11-07.

## ADR-001 — Incremental fork, not a rewrite

**Context.** The upstream EPUB/checkpoint/provider core is mature and heavily
tested; the literary layer is missing.
**Decision.** Keep the upstream application and add `src/literary/` and
`benchmark/literary/`. Patch upstream only at small, tested boundaries
(forbidden renderings in the glossary loader/injector; later an optional style
CLI flag).
**Consequences.** Easier upstream merges; the fork must keep its patches
minimal and re-run the upstream suite. A future rewrite is allowed only if the
fork becomes unmergeable.

## ADR-002 — Host Ollama, not GPU-in-container

**Context.** The RTX 4060 has 8 GB and the host already has a working CUDA
driver, Ollama and a model cache. Docker can see the GPU, but containerizing it
would add a second runtime and cache.
**Decision.** Run Ollama on the host; the app container reaches it through
`host.docker.internal:11434`. The app container does not request GPU access.
**Consequences.** Simpler and faster; the app remains portable; local inference
is not isolated by Docker, but the threat model is a personal machine, not a
multi-tenant server.

## ADR-003 — Source build and localhost-only web UI

**Context.** The upstream Compose pulls a published image; the user needs to
edit code. The default Flask bind is `0.0.0.0`.
**Decision.** `docker-compose.dev.yml` builds from local source, binds
`127.0.0.1:5000`, mounts `src/`, `tests/`, `benchmark/` and
`literary-resources/` read-only, and mounts Calibre read-only.
**Consequences.** Code changes are live without a rebuild; the UI is not exposed
to the LAN by default; the user can still override the bind deliberately.

## ADR-004 — Hierarchical glossary, not one JSON per book

**Context.** The upstream glossary is per book and has no aliases, forbidden
renderings, scope or first appearance. Series terminology drifts.
**Decision.** Versioned YAML under `literary-resources/` with precedence
global < author < universe < subseries < book; compile to the upstream JSON
shape and select per chunk.
**Consequences.** Human-reviewable, diffable, reusable across books; more files
and a compiler, but no database migration. `first_appearance` prevents later
terms from leaking into earlier books.

## ADR-005 — Do not send the whole glossary per request

**Context.** A saga glossary can be thousands of entries. Sending it all wastes
tokens and distracts the model.
**Decision.** Match the chunk against canonical forms and aliases, rank by
frequency/length/approval, cap by tokens (default 900) and entries (50). The
gendered cast block is the only global exception.
**Consequences.** Lower cost and better focus; a term that appears only in a
later chapter is not injected early.

## ADR-006 — Style profiles use the upstream schema

**Context.** The upstream extractor/assembler already has a good schema and an
abstraction linter. A second format would fork the tooling.
**Decision.** Keep `mode`, `context`, `rules`, `translation`, `refinement`; add
`evidence`/`notes` as metadata; compile universe/subseries/book overrides.
**Consequences.** Reuse the linter, preview and web UI; the CLI still needs a
style flag, which is a small future patch.

## ADR-007 — Source-aware segment refinement, not blind full-book rewrite

**Context.** The existing refinement never sees the source and instructs the
model to rewrite an “amateur” draft. ACL 2026 finds refinement gains mainly in
fluency/style, with limited accuracy improvement; monolingual refinement is not
better.
**Decision.** Refine only flagged segments, with source + draft + glossary +
style; constrain edits with a diff/guard; keep the draft on failure. Do not run
the existing full-book refine for production quality.
**Consequences.** Higher quality per token, but more engineering; the existing
refine remains usable for non-critical polishing.

## ADR-008 — Persistent backend queue, not browser queue

**Context.** The upstream batch queue is in `localStorage`; closing the browser
loses it. The backend jobs are per file, not per saga.
**Decision.** `src/literary/queue.py` is the system of record for books,
chapters, states, hashes and costs. The UI should read it.
**Consequences.** Survives restarts, supports saga order and budget gates; the
UI integration is still pending.

## ADR-009 — Deterministic validation before saving

**Context.** LLM judges are biased and expensive; a save path that silently
rewrites can destroy good text.
**Decision.** Run deterministic checks (placeholders, numbers, omissions,
glossary, TOC, EPUB structure) and mark units `needs_review` on blocking
issues. Probabilistic judges are only for review/benchmark, never for automatic
rewrites.
**Consequences.** Safer output; some false positives; human review is required.

## ADR-010 — No cloud spend without approval; DeepSeek is opt-in

**Context.** A cloud bill is easy to run up; DeepSeek's policy allows training
on API data by default and has no published ZDR tier.
**Decision.** Default to local. Require explicit approval and a hard budget for
any cloud run. Do not send copyrighted books to DeepSeek without informed
consent. Do not use key rotation to evade limits.
**Consequences.** Slower initial experiments; avoids legal/privacy surprises.

## ADR-011 — No Calibre database writes

**Context.** The library is the user's archive; a bad write can corrupt
metadata or lose data.
**Decision.** Read `metadata.db` with SQLite `mode=ro`; never write. Correct
metadata on generated EPUB copies; if Calibre needs updating, use the official
`calibredb` flow only after explicit approval.
**Consequences.** The original library stays intact; the queue uses
`series.yaml` as the source of truth for order.

## ADR-012 — EPUBCheck is a gate, but not installed yet

**Context.** The machine has Java 8; EPUBCheck 5.x needs Java 11+. Structural
validation is implemented, but it is not a substitute for EPUBCheck.
**Decision.** Use the structural validator now; add EPUBCheck after installing
a modern JDK and make it a completion gate.
**Consequences.** The POC can validate structure today; final publication
remains blocked until EPUBCheck passes.

## ADR-013 — Narrative memory is proposed, not built

**Context.** The user wants continuity across chapters and books. A memory
system sounds sophisticated but can add cost and spoilers if not measured.
**Decision.** Design the schema and relevance/spoiler rules; implement only
after a chapter-seam experiment shows a measurable gain over glossary + style +
local context.
**Consequences.** Avoids complexity for its own sake; the glossary and style
layers carry continuity in the first production pass.

## ADR-014 — Do not choose a model by parameter count

**Context.** The pilot showed a 12B specialized model making worse semantic
errors than an 8B generalist, and a 14B model not uniformly beating the 8B.
**Decision.** Choose by the six-dimension rubric + gates, cost per accepted
chapter, and stability over consecutive chapters. Vendor benchmarks are
directional only.
**Consequences.** The final selection waits for Phase 4; local and cloud
winners may differ by book/saga.
