# Roadmap

## Status

| Phase | Status | Evidence |
|---|---|---|
| 1. Discovery and research | **Complete** | `AUDIT.md`, `ENVIRONMENT.md`, `MODEL_RESEARCH.md` |
| 2. Architecture and planning | **Complete** | `ARCHITECTURE.md`, `COST_MODEL.md`, `LITERARY_RUBRIC.md` |
| 3. Safe local proof of concept | **Complete** | `POC.md`; Docker, inventory, resources, queue, cost, validation, benchmark harness |
| 4. Full model benchmark | **Partial** | Installed models tested; Hy-MT2/Index/cloud still need approval |
| 5. Editorial preparation | **Partial** | Initial glossary + style profiles; needs expansion and review |
| 6. Pilot translation | **Not started** | Requires an approved pilot book/chapter and budget |
| 7. Production | **Not started** | Requires Phase 6 acceptance |

## Phase 4 — benchmark and model decision

| # | Task | Why | Effort | Dependency | Acceptance |
|---|---|---|---|---|---|
| 4.1 | ~~Approve and download Hy-MT2-7B Q4_K_M and Index-Translate-9B Q4_K_M~~ | **Done 2026-11-07.** The two strongest local candidates cannot be selected without testing | S (download) + M (test) | User approval for ~10 GB download | Both installed from the official GGUF repos and run at 8K; VRAM and latency recorded. 16K added CPU offload and is not the default |
| 4.2 | Curate 12–20 excerpts with human-reviewed categories and 2 consecutive passages per book | The current 15 are auto-selected and isolated | M | Local EPUBs | Corpus reviewed; category and continuity coverage documented |
| 4.3 | Align official PT references for Farseer 1 and Sun Eater 1; keep the Lonesome Dove draft as a separate revision aid | chrF/reference-based comparison needs alignment | M | Official PT editions; user's unreviewed Lonesome draft | Paragraph alignment with confidence; no fan translation or unreviewed draft as gold |
| 4.4 | Run the local benchmark with native and glossary/style rounds | Separate model capability from instruction-following | M | 4.1–4.3 | **Partially done 2026-11-07.** 15 excerpts for TranslateGemma, Qwen3 8B/14B, Hy-MT2 and Index; single run, no repeats. Curated corpus and reference alignment still pending |
| 4.5 | Approve a cloud budget and run Gemini 3.8 Flash, DeepSeek V4.1 Flash, GPT-6 Luna, Claude Haiku 5.5 | Cloud decision needs PT-BR evidence, not just vendor claims | M | User budget approval | Actual tokens/cost logged; hard cap enforced |
| 4.6 | Blind judge + human spot-check | Avoid LLM-judge self-preference and fluency bias | M | 4.4–4.5 | Six-dimension scores, gates, confidence, disagreement reported |
| 4.7 | Select local and cloud winners | Decision, not more data collection | S | 4.6 | Written recommendation with evidence and cost per accepted chapter |

**Approval required before 4.5. Do not start it automatically.**

## Phase 5 — editorial preparation

| # | Task | Why | Effort | Dependency | Acceptance |
|---|---|---|---|---|---|
| 5.1 | Expand the Farseer glossary using the three official PT editions | Names/terms are verified; many secondary terms are still missing | M | Read-only library | Reviewed terms with source_reference and confidence |
| 5.2 | Review and expand the Lonesome Dove glossary | Names/places are provisional from the user's unreviewed draft; regional/fauna vocabulary still needs decisions | M | Read-only library; user review | Approved terms + forbidden renderings |
| 5.3 | Expand the Sun Eater glossary | Only book 1 PT is available; later terms need provisional marking | M | Read-only library | Series glossary with first_appearance |
| 5.4 | Validate the provisional Hobb subseries profiles against 3 chapters each | Current profiles are structural priors | M | EN books | Revised profiles or explicit “provisional” status |
| 5.5 | Build the Rain Wild omnibus split manifest | One EPUB contains four novels | S | EPUB structure | **Deferred by the user.** If revisited: four book units with chapter boundaries |
| 5.6 | ~~Produce and apply a Calibre metadata correction plan for the target authors~~ | **Done 2026-11-07.** Calibre main novels lacked series/index; Lonesome PT had `author_sort = Unknown` | S | Calibre inventory; user authorization granted | 28 records applied through `calibredb`, 0 mismatches, backup kept, `targets.json` regenerated |
| 5.7 | Define the PT-BR conventions checklist | Global style/terminology policy | S | Editorial review | Approved `global/pt-br-conventions.yaml` |

## Phase 6 — pilot translation

| # | Task | Why | Effort | Dependency | Acceptance |
|---|---|---|---|---|---|
| 6.1 | Choose pilot: one chapter of Sun Eater 2 or Lonesome Dove | Test the whole pipeline on a representative text | S | Phase 4/5 | Written pilot brief |
| 6.2 | Compile glossary + style + cost preview | Preflight | S | Resources | `estimated_cost` and budget cap stored |
| 6.3 | Translate with the selected local model | Quality/cost baseline | M | 4.7 | Checkpoints per chapter; no lost work |
| 6.4 | Validate and selectively refine | Test the quality gate | M | 6.3 | Gate report; no silent fallback |
| 6.5 | Rebuild EPUB, run structural check/EPUBCheck | Reader safety | S | 6.4 | Valid EPUB; TOC labels correct |
| 6.6 | Read in Calibre and KOReader | Real-world check | S | 6.5 | Notes on layout, TOC, italics, links, notes |
| 6.7 | Editorial review and acceptance | Human decision | M | 6.6 | Signed-off pilot or rejection with reasons |

**No full-book translation before 6.7 is accepted.**

## Phase 7 — production queue

| # | Task | Why | Effort | Dependency | Acceptance |
|---|---|---|---|---|---|
| 7.1 | Wire the persistent queue to upstream `translation_id` | The queue must actually drive jobs | M | 6.7 | A paused/resumed book keeps chapter state |
| 7.2 | Add budget gate and per-chapter cost logging | Avoid surprise spend | S | 7.1 | Job refuses to exceed cap |
| 7.3 | Add the review/approval UI | Human gate | M | 7.1 | Chapter can be approved/rejected without re-running the book |
| 7.4 | Automate EPUBCheck | Structural safety | S | JDK 17 + EPUBCheck | CI/queue gate |
| 7.5 | Add saga-level reports | Editorial control | M | 7.1 | Per-book/per-series quality and cost |
| 7.6 | Translate the first approved saga in order | Production | L | 7.1–7.5 | All acceptance criteria below |

## Required approvals

1. **Model downloads:** Hy-MT2-7B and Index-Translate-9B GGUF (~10 GB).
2. **Cloud spend:** any API call beyond a trivial smoke test; set a hard cap.
3. **Calibre writes:** none planned; if metadata correction is desired, use
   `calibredb` only after explicit approval and on a copy.
4. **Full-book translation:** only after the pilot is accepted.
5. **Provider privacy:** DeepSeek may train on API data by default; explicit
   informed consent is required before sending book text.

## Success criteria mapping

| User criterion | How this architecture addresses it | Status |
|---|---|---|
| Run locally with Docker | Dev Compose builds local source; healthcheck; host Ollama | Proven |
| Modify code and test | Source bind mount; 17 new tests; full suite baseline | Proven |
| Calibre intact | Read-only SQLite; no writes; read-only mount | Proven |
| Identify books/series | Inventory + `series.yaml` | Proven on 28 target records |
| Persistent glossary per saga | Hierarchical YAML + compiler | Initial resources created |
| Terminology across books | `first_appearance`, aliases, forbidden, versionable YAML | Initial; needs expansion |
| Style differences preserved | Universe/subseries/book profiles | Initial; provisional subseries |
| Resume interrupted translation | Upstream checkpoints + new queue | Upstream proven; queue integration pending |
| Valid, readable EPUB | Structural validator + upstream reconstruction | Proven structural; EPUBCheck pending |
| Catch important errors | Deterministic gates + rubric | TOC corruption caught; pilot errors documented |
| Compare models objectively | `benchmark/literary` + rubric | Harness + pilot done; full round pending |
| Know cost before cloud | `src/literary/cost.py` + budget gate design | Estimator done; gate pending |
| Review without reprocessing whole book | Chapter/chunk queue + term-fix | Upstream chunk resume; UI/queue pending |
| Better than naive chunk translation | Source-aware selective refine + glossary/style | Designed, not yet implemented |
