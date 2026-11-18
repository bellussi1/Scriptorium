# Active context

Handoff between sessions. Read this first; update it before you stop. It must
describe the real repository, not a plan. Status as of 2026-11-18 (01:36 local):
revalidate with `git status` and `git log` before acting. Older
handoffs are in git history (this file was compacted on 2026-11-12).

## Now

- **Gemini 3.8 Flash funded, Farseer official alignment complete, and `#4 Fool's Errand` actively translating (2026-11-18 01:36 local):**
  - **Billing & guard fix:** Funded `GEMINI_API_KEY` (`R$ 30` Prepay wallet top-up + `US$ 40` Google Developer Program monthly credit; `data/budgets.json` `gemini.cap_usd = 45.0`), verified `HTTP 200 OK` on `gemini-3.8-flash` (`thinkingBudget: 0`), and fixed `src/core/llm/providers/gemini.py` so HTTP `402` / `"prepayment"` / `"billing"` errors never raise `ContextOverflowError` (failing fast instead of chunk-splitting). Also fixed `compile_for_book` in `src/literary/resources.py` to match apostrophe/hyphen slug variants (`fool-s-errand` -> `fools-errand` order `7.0`) and added `the-rain-wild-chronicles` (`order: 13`) to `realm-of-the-elderlings/series.yaml`.
  - **Official Brazilian *Farseer Trilogy* editorial alignment:** Audited the official PT-BR editions (`Calibre 94/92/71`) and aligned `literary-resources/robin-hobb/realm-of-the-elderlings/` (`glossary.yaml`, `characters.yaml`, `style.yaml`, `tawny-man/`, `fitz-and-the-fool/`): `White Prophet` -> `Profeta Branco`, `Catalyst` -> `Catalisador`, `Old Blood` -> `Sangue Antigo`, `Piebald` -> `Malhado` (`Piebald Prince` -> `Príncipe Malhado`), `Changer` -> `Alterador`, `Withywoods` -> `Floresta Mirrada`, `Tilth` -> `Lavra`, `Neatbay` -> `Baía Limpa`, `Moonseye` -> `Olho da Lua`, `Blue Lake` -> `Lago Azul`, `Sooty` -> `Fuligem`, `Girl-on-a-Dragon` -> `Garota no Dragão`, `Verity-as-Dragon` -> `O Dragão de Verity`, `Skill-coterie` -> `círculo de Talento`, `Sacrifice` -> `Sacrifício`, `The Fool` -> `O Bobo`/`Bobo`, lowercase Six Duchies titles (`rei`, `príncipe`, `rainha`, `lorde`, `Lorde Golden`, keeping `Lady Patience`), Brazilian `travessão` dialogue formatting, and bare `<i>...</i>` italics for *Talento*/*Manha* telepathy. Resource validation passes with `0` errors (`python -m pytest -q tests/literary tests/unit/test_gemini_response_parts.py`: `421 passed`).
  - **Live 10-excerpt verification pilot (`gemini-3.8-flash`):** `data/benchmark/hobb-pilot-cloud/20261118T043032Z/gemini-3.8-flash.jsonl` scored **`name_recall = 1.0000`**, `chrF = 0.7298`, `0` errors, `4.65 s` latency, `$0.02617` total (`$13.02 / 1M` words), documented in `docs/project/reviews/hobb-gemini-pilot-2026-11-18.md`.
  - **Queue switched & live run started:** Retired partial Ollama `job #40` (`cli_bcf8480f`) on book `#4`, switched all `7` pending *Realm of the Elderlings* queue books (`#4, #6, #5, #16, #17, #18, #33`, `2.40M` words, estimated `$22.10` total) to `gemini` / `gemini-3.8-flash`, and launched `scripts/queue_runner_agent.py` + `request_run(mode="next")` (`--max-books 1 --stop-on-review --parallel 1`). **`#4 Fool's Errand` (`job #41`, `translation_id: cli_93ddf44e`) is actively translating** from `data/calibre/prepared/fool-s-errand.epub` (`chunk 1/851` fresh); do **not** restart `translatebook-literary-dev` while running.

- **Liveship Traders polish & Robin Hobb Gemini comparative pilot (2026-11-18 early morning local):**
  - **Restored queue & stopped redundant job:** Per user instruction, cancelled the fresh `Ship of Magic` re-translation (`job #41`), restored the pre-reset DB (`data/literary_queue.db`), queue logs (`83` files), and completed artifacts (`Sun Eater 2–7`, `Lonesome Dove`, `Liveship 1–3`), and updated `13` defective DB rows (`source_path`/`source_hash`) to point to the sanitized EPUBs in `data/calibre/prepared/`.
  - **Polished Liveship Traders `#2`, `#3`, `#1` for KOReader (`EPUBCheck 0/0/0`):** Added `repair_translated_pdftohtml_epub` in `src/literary/source_prep.py` (strips translated `pdftohtml` footers, `Hobb, Robin` running headers, translated `Document Outline` files, and `&lt;/?KTRANSLATION&gt;` leaks; rejoins split sentences; restores all missing/merged chapter headings across *Ship of Magic* [37], *The Mad Ship* [41 NCX / 42 headings], and *Ship of Destiny* [42]; fixes heading typos and rebuilds `toc.ncx` + OPF/NCX UIDs). Ran `repair_translated_pdftohtml_epub` -> `repair_progressive_in_epub` -> `repair_invalid_ids_in_epub` -> `repair_epubcheck_hygiene_in_epub` -> `repair_reading_epub(apply_terms=False)` -> `standardize_book_opf` on all three books, promoted `#2`, `#3`, `#1` to `completed`, archived intermediates (`translated_files/archive/intermediates-2026-11-18/`), and rebuilt `translated_files/kindle/` (`10` books in `manifest.csv`; all 3 Liveship Kindle EPUBs verified `EPUBCheck 0/0/0`).
  - **Gemini Pro support & Hobb comparative pilot:** Updated `src/core/llm/providers/gemini.py` (`gemini-2.5-pro` uses `thinkingBudget: 128`, `gemini-3.1-pro-preview` omits `thinkingConfig`, HTTP 400 `"thinking"` fallback retry without `thinkingConfig`, and `thoughtsTokenCount` included in `completion_tokens`), added Pro pricing to `src/literary/cost.py`, and added `--max-cost-usd` budget enforcement to `scripts/benchmark_cloud.py`. Ran live `Index-Translate-9B` on `10` challenging Farseer excerpts (`data/benchmark/literary/pilot_hobb_chapter.jsonl`, `chrF 0.7303`, `name_recall 0.9167`, `0` cost); live calls to `gemini-3.8-flash` and `gemini-2.5-pro` hit `HTTP 402 Payment Required` (`Your prepayment credits are depleted`) on both `.env` keys (`...EYNg` and `...mmqA`, `$0.00` spent). Side-by-side comparison vs. the `2026-11-10` `Gemini 3.8 Flash` run (`chrF 0.7126`, `name_recall 0.9800`) is documented in `docs/project/reviews/hobb-gemini-pilot-2026-11-18.md`. Queue runner (`scripts/queue_runner_agent.py`) stays idle until the user provides an active AI Studio key or selects local Index-9B.

- **Source EPUB prep & cross-series quality baseline (`4eff094`, 2026-11-18):**
  - Added `src/literary/source_prep.py` (`prepare_source_epub`, `13` prepared EPUBs under `data/calibre/prepared/`, `EPUBCheck 0/0/0` on Liveship 1–3, `The Golden Fool`, `Fool's Fate`), `repair_epubcheck_hygiene_in_epub` in `src/literary/repair.py`, expanded `PROGRESSIVE_GERUNDS` + `_infinitive_to_gerund` fallback in `src/literary/progressive_repair.py`, generalized `src/literary/reading_repair.py` & `src/literary/polish.py` across all series, refreshed `data/calibre/targets.json` (`47` books including `Empire of Silence` id `439`), extracted EN/PT editorial samples in `data/editorial_samples/`, and enriched `literary-resources/` (`49` files valid under `resources validate`).

- **Fixed badge column alignment in `#files` (`5a0bd29`, 2026-11-15; no Docker restart):**
  - Switched `.file-name-cell` in `src/web/static/scss/_ui-polish.scss` to a 3-column CSS Grid (`minmax(180px, 42ch) 58px 144px`), pinning `.is-final` (`Final`) to track 2 and role badges (`.file-artifact-badge:not(.is-final)`) to track 3 with centered pill widths so badges form vertical columns across every row regardless of filename length.
  - Restored standard `table` / `table-header-group` / `table-row-group` / `table-row` display geometry on `.file-table` in `src/web/static/scss/_literary-theme.scss`, aligned `#tab-files` Actions `<th>` width to `160px` (`translation_interface.html`), bumped `app.css?v=20261115-files-cols`, rebuilt `src/web/static/css/app.css`, and verified `npm run build:css`, `npm run typecheck`, `npm run test:js` (`7/7`), and `pytest -q tests/test_frontend_i18n.py` (`22 passed`).

- **Compact Web UI density for 100% zoom (`b818319`, 2026-11-15; no Docker restart):**
  - Widened `.container` (`1200px` -> `1440px`) and compacted shell typography/padding across `src/web/static/scss/_literary-theme.scss`, `_ui-polish.scss`, and `_queue.scss` (`body` `13px`, tighter `.header` / `#topTabNav` / `.card-header` / `.card-body`, `--ui-control-h: 32px` inside `@layer compact-ui`, smaller Translate upload zones, denser Queue summary strip/filters/table rows/action buttons, and slimmer `--q-*` tokens + Review drawer padding) so 100% browser zoom matches ~75% zoom density without unnecessary vertical scrolling.
  - Bumped stylesheet cache-buster in `src/web/templates/translation_interface.html` (`app.css?v=20261115-compact`) and rebuilt `src/web/static/css/app.css`. Verified `npm run build:css`, `npm run typecheck`, `npm run test:js` (`7/7`), and `pytest -q tests/test_frontend_i18n.py tests/unit/test_literary_queue_routes.py` (`54 passed`). Static CSS changes are served immediately from disk without restarting `translatebook-literary-dev`.

- **Web UI/UX & Queue Review Drawer polish (`549516c` / `78ab97d`, 2026-11-15; no GPU/cloud/Docker restart):**
  - **SCSS & theme token cleanup:** Removed orphaned `.header .logo-text` rules from `src/web/static/scss/_style.scss` and `src/web/static/scss/_literary-theme.scss`, wired `.header .logo-wordmark` into the Zilla Slab display scale, replaced undefined CSS variables (`--bg-light`, `--border-color`, `--primary`, `--text-light`) in `_style.scss` and `translation_interface.html`, fixed the conflicting `.btn-primary` rule in `_ui-polish.scss`, and aligned `html.dark { --primary-light: #2563eb; }` in `_literary-theme.scss`.
  - **De-inlined status panels & badges:** Removed hardcoded light-mode hex colors, pastel gradients, and `1.5rem`/pill radii from `#openrouterCostGrid`, `#ttsProgressSection`/`#ttsProgressBar`, `#apiEndpointBadge`, `#openaiEndpointBadge`, `#thinkingModelWarning`, `#notifyStatusBadge`, and `#glossaryEditorDeleteBtn` in `src/web/templates/translation_interface.html` (and `ttsProgressBar` error color in `src/web/static/js/index.js`), moving them to token-backed SCSS classes in `_literary-theme.scss` and bumping the CSS cache-buster (`app.css?v=20261115-ui-ux`). Rebuilt `src/web/static/css/app.css`.
  - **Actionable 2-minute Queue Review Drawer:** Extended `src/literary/queue_insights.py` (`_compiled_forbidden_forms`, `forbidden_form_hits`, `pt_pt_blocking`, `pt_pt_total`, `review_samples` per spine doc), removed duplicate local `escapeHtml` in `src/web/static/js/queue/queue-manager.js`, added a localized 5-check **Review checklist** plus flagged occurrence samples in `#queueQualityDrawer` (`_queue.scss`, `locales/{pt-BR,en}/queue.json`), and added coverage in `tests/literary/test_queue_insights.py`.

- **Calibre-aligned OPF metadata, tags & synopses standardization (2026-11-15; no GPU/cloud calls):**
  Added `src/literary/metadata.py` (`tags_for`, `infer_calibre_library`, `standardized_title`,
  `standardized_description`, `standardize_book_opf`, `standardize_completed_outputs`) and
  `python -m src.literary.cli metadata standardize`. Wired `standardize_book_opf` into
  both `src/literary/queue_runner.py` (all completed books, series or standalone, before
  `validate_epub_pair` / `EPUBCheck`) and `src/literary/kindle.py` (`build_kindle_library`),
  and fixed Windows in-place ZIP `PermissionError` plus NCX `<docTitle><text>` syncing
  in `src/literary/epub.py`.
  - **Applied to live completed EPUBs:** Updated all 7 `translated_files/*.refined.epub`
    files and rebuilt `translated_files/kindle/` (`7` EPUBs, `manifest.csv`, `README.md`)
    using Calibre (`C:\Users\Bellussi\Biblioteca do calibre\metadata.db`) read-only;
    Calibre's database was not modified.
  - **Conventions applied:** `<dc:subject>` normalized to Calibre genres (`Fiction`,
    `Speculative Fiction`, `Science Fiction`, `Space Opera`, `Science Fantasy` for Sun
    Eater; `Fiction`, `Historical Fiction`, `Western`, `Classic` for Lonesome Dove;
    macro-universe tags preserved where present) plus `PT-BR` and `Scriptorium` (removing
    `Brazilian Portuguese`, `Machine Translation`, `no data`, `EN`, BISAC, and redundant
    series tags). Disambiguated untranslated titles (`Lonesome Dove (PT-BR)`) in
    `<dc:title>`, `calibre:title_sort`, and NCX `<docTitle><text>`. Preserved existing
    PT-BR synopses while stripping legacy Scriptorium URLs, replacing `"Devorador de Sóis"`
    with `"Sun Eater"`, appending `"Tradução em português brasileiro via Scriptorium."`,
    and supplying a curated PT-BR synopsis for *Disquiet Gods* (`Deuses Inquietos`).
  - **Verification:** `EPUBCheck` exited `0` (`0` fatals, `0` errors) on all 7
    `*.refined.epub` files and all 7 `translated_files/kindle/**/*.epub` files
    (`Ashes of Man` and `Shadows Upon Time` keep 1 pre-existing `OPF-086c` `xsd` prefix
    warning each); `ruff check` on all 7 added/modified files passed (`0` errors);
    `pytest -q tests/unit tests/literary tests/test_frontend_i18n.py` passed (`2656 passed`).

- **Proper-noun & title keep-in-English alignment (2026-11-15 early morning local; no GPU/cloud calls):**
  Owner defined glossary/style preference: keep capitalized proper nouns,
  settlements/cities, states/realms, organizations, offices, and formal titles
  paired with names in English (`policy: keep`), while preserving official
  Farseer PT-BR canon (`Talento`, `Manha`, `Bobo`, `Ferreirinho`, `Seis Ducados`,
  `Torre do Cervo`, `Cervo`, `Vara`, `rio Cervo`, `Ilhas Externas`, `ilhéu`,
  `Navio Vermelho`, `Forjados`, `Antigos`, `Outros`, `Assassino`, `chyurda`) and
  adapting only lowercase demonyms (`jamailliano`, `chalcedeano`) and lowercase
  common-noun heads (`rio Rain Wild`, `pilar do Talento`, `rio do Talento`).
  - **Global rules:** Added `literary-resources/global/style.yaml` (`proper_nouns`
    dimension, clean under `lint_instruction`) so every series—including `Malazan`
    (`rules=1`)—inherits the rule automatically, and updated
    `literary-resources/global/pt-br-conventions.yaml` (`proper_nouns`,
    `forms_of_address`) to match.
  - **Robin Hobb (`realm-of-the-elderlings`):** Switched alias titles to English
    in `characters.yaml` (`King Shrewd`, `Prince Verity`, `Prince Regal`,
    `Prince Chivalry`, `Prince Dutiful`), and switched non-Farseer capitalized
    terms/titles/places/groups to `policy: keep` across `liveship-traders/`,
    `tawny-man/`, `rain-wild-chronicles/`, and `fitz-and-the-fool/` (`Liveship`/
    `Liveships`, `Trader`/`Traders`, `Old Traders`, `New Traders`,
    `Bingtown Traders`, `Rain Wild Traders`, `Pirate Isles`, `Satrap Cosgo`,
    `She Who Remembers`, `Captain Leftrin`, `Lord Golden`, `Pale Woman`,
    `Black Man`, `Old Blood`, `Piebalds`, `Catalyst`, `White Prophet`/`Whites`),
    plus `chapter-titles/ship-of-magic.yaml` (ch. 2, 24, 36) and
    `robin-hobb/tawny-man/chapter-titles/fools-errand.yaml` (ch. 8).
  - **John Gwynne (`the-banished-lands`):** Updated `glossary.yaml` to keep
    capitalized places, groups, titles, and events in English (`Banished Lands`,
    `Faithful`, `Fallen`, `The Faithful and the Fallen`, `Land of the Faithful`,
    `Otherworld`, `White-Wing`/`White-Wings`, `War of Treasures`, `Age of Lore`,
    `Separate Ones`, `Sons of the Mighty`, `Great Tyrant`), leaving lowercase
    `giant` and `starstone` translated. `joe-abercrombie/the-first-law` left
    untouched.
  - **Active run handling (`Ship of Magic` #2):** Let the running Index-Translate-9B
    job finish rather than restarting mid-run; already-translated early chunks
    carrying `navio vivo`, `Comerciante`, `Sátrapa`, and `Ilhas Piratas` will be
    normalized in post-translation `--fix-terms` / revision alongside
    `chapter_headings`. Pending books `#3, #1, #4, #6, #5, #16-18, #33, #29-30, #19, #31`
    all pass `queue plan` with `issues: []`.
- **Polish & glossary pass (2026-11-14 late evening local; no GPU/cloud calls):**
  Backups in `data/tmp/polish-pass-2026-11-14/` (`literary_queue.before.db`,
  `Lonesome Dove (pt-BR) - fixed-v2.before.epub`, and six `*.refined.before.epub`).
  - **Queue state:** `Ship of Magic` (book 2, priority 22) is `translating` on
    Index-Translate-9B. Do NOT restart `translatebook-literary-dev`. The seven
    previously completed books (`Lonesome Dove` #32 and *Sun Eater 2–7*: #10, #8,
    #11, #7, #9, #13) were polished in place and exported to `translated_files/kindle/`
    (`queue export-kindle`, 7 entries in `translated_files/kindle/manifest.csv`).
  - **Rule & audit fixes:** Expanded `PROGRESSIVE_GERUNDS` in
    `src/literary/progressive_repair.py`; added `ptbr.pt_quilometro` and
    expanded `ptbr.pt_tu_preterito` / `ptbr.pt_tu_futuro` in `src/literary/ptbr.py`;
    added `pt_quilometro` / `pt_tu` / `pt_tu_futuro` to `SAFE_CODES` + 2p tables in
    `src/literary/ptbr_revise.py`; preserved non-empty `accepted_targets` in
    `write_glossary_json` (`src/literary/resources.py`) and
    `_load_glossary_snapshot` / `_term_audit` (`scripts/audit_book.py`).
  - **Lonesome Dove (#32):** Updated `literary-resources/larry-mcmurtry/lonesome-dove/glossary.yaml`
    (genders for `Lorie`, `Zwey`, `Ellie`, `Peach`; dict `accepted_targets` for
    `July Johnson`, `Needle Nelson`, `Indian`; added `Comanche`) and recompiled
    `data/compiled/lonesome-dove-glossary.json` (`44` compiled entries). Converted
    123 `<blockquote class="calibre_4|6">` to `<p>` (`index_split_112/108/075/056.html`),
    localized `toc.ncx`, and fixed `Bolívar`, all-caps sign, `rebanho`, `Lorie`
    agreement, progressive periphrases, and 2p leftovers; promoted the verified
    artifact to `translated_files/Lonesome Dove (pt-BR).refined.epub` (and updated
    `refined_output` in `data/queue-runs/lonesome-dove.report.json`). Passed
    `validate_epub_pair` (`blocking: 0`), `EPUBCheck` (`0/0/0`, down from 248
    errors), and `audit_book.py --book-id 32 --no-cloud` (`passed: true`).
  - **Files tab cleanup (`translated_files/`):** Moved 21 intermediate EPUBs
    (`raw`, `- fixed`, `- fixed-v2`) across the 7 completed books plus 2
    `Destructive-24h-*` test EPUBs into `translated_files/archive/intermediates-2026-11-14/`
    so `#files` (`FileService`) lists only the 7 final `*.refined.epub` editions.
  - **Sun Eater 2–7 (.refined.epub):** Applied progressive repair, `_swap_text`,
    `contigo` / preposition+`ti`, `estava a sonhar`, and split chapter-header/TOC
    repairs (`Ashes of Man` ch. 19 `023_chapter_019.xhtml` / `toc.ncx` / `nav.xhtml`;
    `Shadows Upon Time` ch. 13 `017_Chapter_013.xhtml` / `nav.xhtml`). Updated
    `validation` + `epubcheck` in all six `data/queue-runs/<slug>.report.json`
    files; all six pass `validate_epub_pair` (`blocking: 0`), `EPUBCheck` (`0`
    fatals / `0` errors), and `audit_book.py --no-cloud` (`passed: true`).
  - **Realm of the Elderlings glossaries:** Added
    `fitz-and-the-fool/{characters,glossary}.yaml` and
    `rain-wild-chronicles/{characters,glossary}.yaml` (updated 2026-11-15 to
    `74` and `93` compiled terms under the English proper-noun/title policy).
    Remaining note: `Ship of Magic`, `The Mad Ship`, and `Ship of Destiny`
    sources still carry a `file:///C|/Documents and Settings/Tony/...` footer
    (run `chapter_headings` post-pass after translation); `Malazan` still has no
    glossary (inherits `global/style.yaml` `proper_nouns`).
- **Earlier 2026-11-14 notes:** Lonesome Dove (book 32) ran Job 36 (`cli_ad52c2c1`,
  resumed after shutdown at ch. 71/1261 with Ollama + `scripts/queue_runner_agent.py`
  and completed before approval). Priority queue order after `Ship of Magic` (2):
  `The Mad Ship` (3), `Ship of Destiny` (1), `Fool's Errand` (4), `The Golden Fool` (6),
  `Fool's Fate` (5), `Fool's Assassin` (16), `Fool's Quest` (17), `Assassin's Fate` (18),
  `The Rain Wild Chronicles` (33, priority 13). Malazan rows 19–28 sit below at priorities 12–3.

- **Front (2026-11-13 23:45 local):** slop pass applied (violet accents to the theme accent, labels to 12px, muted grey darkened, side-tab borders to 1px). Static CSS and JS are live on reload. The template version bump (`index.js?v=20261113-slop-pass`) applies only after the app container restarts. Do not restart it while a queue book runs, because `docker exec` translations die with it.
- **Decision 2026-11-13: retranslate Demon in White, Howling Dark, Kingdoms of Death and Ashes of Man**
  from source, one at a time, without the refine pass (Scenario A of
  `docs/project/reviews/local-model-ceiling-2026-11-12.md`). `scripts/queue_runner_agent.py` now passes
  `--no-refine`; that takes effect when the agent restarts, which waits for Shadows Upon Time to finish.
  Order: Demon (priority 1000000), Howling, Kingdoms, Ashes. Each run is gated before the next one starts.
  **Chain finished 2026-11-14 04:11 local.** All four books passed the gate and wait for review (`needs_review`).
  Kingdoms passed at 01:30 (pt-PT 20.33 against 9.94, forbidden 0). Ashes passed at 04:11 (pt-PT 20.32 against 17.5;
  one forbidden rendering, `Chantry` to `Cantaria`, which the baseline also has, so the gate allows it).
  pt-PT is recorded, not gated: Howling (13.86 against 6.75) and Kingdoms are about double their baselines.
  Check the pt-BR wording in review before approving. Nothing is committed for this run.
  Demon and Howling passed the gate earlier. The first Kingdoms run failed
  (`Chantry` ×3 against baseline 0; pt-PT 17.55 against 9.94); its output is in
  `data/tmp/retranslation-backup-2026-11-13/rejected-kingdoms-2026-11-13/`.
  **The earlier pt-BR fix never reached any run.** `_compile_assets` (`src/literary/queue_runner.py`)
  rewrites `Custom_Instructions/queue-<slug>.yaml` at each run start from the style source, so the hand
  edits were overwritten. The fix now lives in `literary-resources/christopher-ruocchio/sun-eater/style.yaml`
  as rule `target_variety` (committed in `74a9668`).
  Demon 11.08 (baseline 10.07) and Howling 13.86 (baseline 6.75) ran without that rule.
  **Chain re-run 2026-11-13 10:05 local, after the first Demon run halted.** The first run (06:04 to
  10:01) failed the pt-PT gate (14.43 per 100k against a baseline of 10.07). That baseline was a
  post-edited book (refine plus the pt-BR stage); the new run had neither, so the check was not
  like-for-like. The rejected Demon output is
  in `data/tmp/retranslation-backup-2026-11-13/rejected-demon-2026-11-13/`. Script:
  `scratchpad/retranslate_chain.py` (session scratchpad). Log: `chain/chain.log`. State: `chain/state.json`
  (`halted` says why it stopped). Gate per book: EPUBCheck 0, no more forbidden renderings, glossary
  coverage at most 0.01 below baseline, English leakage at most 0.01, length ratio 0.80 to 1.20.
  If it halts, the new output is `needs_review` and the old one is in `backup/outputs` and `backup/replaced`.
  Backups (DB and the current outputs of the four books): `data/tmp/retranslation-backup-2026-11-13/`.
  Until the new versions are approved, the old ones are the backups, not the library state.
- **Deterministic fixes 2026-11-14 (after the cloud audit, no approval):** Demon (`Veja IMPÉRIO SOLLANO`, `WILLIAM O ADVENTO`);
  Ashes (`FOGO PÁLIDO`, `ALMIRANTE`, `NO IMPÉRIO SOLLANO`, `LÉXICO` in place of `LEXYCONO`, chapter titles in nav, English `<title>` to pt-BR);
  Shadows (chapter titles in nav, English `<title>` to pt-BR). Backups: `data/tmp/fixes-2026-11-14-backup/`.
  Audit (deterministic): all six pass after the detector fix below. The Kindle export is not rebuilt.
- **Detector fix 2026-11-14 (owner approved "ajustar"):** two false positives in Ashes were detector bugs, not text errors.
  (1) `scripts/audit_book.py` counted forbidden forms case-insensitively, so the verb `cantaria` ("would sing") hit the
  forbidden `Cantaria`; it now uses `count_forbidden_occurrences` from `src/literary/per_file_audit.py`, which the per-file scan
  already used. (2) `FOR` was an English all-caps token everywhere; it is now skipped after `SE`, `QUE`, `QUANDO`, `CASO`,
  `ENQUANTO` (`english_caps_tokens`). Tests: `tests/literary/test_audit_precision.py`; full `tests/literary` suite: 398 passed.
  Ashes passes the deterministic audit and the cloud audit (about $0.0014). Its one judge meaning item is the false ISBN; the
  gate tolerates it. Ashes is still `needs_review`; nothing was approved.
- **Meaning fixes 2026-11-14 (owner approved the judge's meaning errors):** Demon ch. 9 `mobiliário branco` → `paredes brancas`
  (source: "Gray-walled and white"); Howling ch. 17 `que víssemos` → `que tínhamos visto`; Kingdoms ch. 5 `incomparável` →
  `incontável`; Kingdoms ch. 33 `cresciam` → `rangiam`. Judge findings rejected as false: the Ashes copyright ISBN is in the source,
  and Howling ch. 17 keeps "maybe" as `talvez umas cem passos`. Backups: `data/tmp/meaning-fixes-2026-11-14-backup/`.
  Deterministic audit: Demon, Howling and Kingdoms pass. Cloud re-judge (Haiku, about $0.004 in total): all three pass with 0 meaning
  errors. Ashes's only judge meaning item was the false ISBN.
- **Corrections 2026-11-14 (owner: "corrija todos"):** accents across the six books: `telegrafo` → `telégrafo`, `animalculo` →
  `animálculo`, `SILENCIO`/`Silencio` → `SILÊNCIO`/`Silêncio`, `IMPERIO`/`Imperio` → `IMPÉRIO`/`Império`, `A MUSICA` → `A MÚSICA`,
  `FOGO PALIDO` → `FOGO PÁLIDO` (Ashes contents), `Unico` → `Único` (Shadows ch. 79). Glossary form `Sollan` → `Sollano`
  (adjective agreed: `sollanos`, `sollana`) in all 19 places, including `oficiais Sollan` (Demon ch. 81). `nave-nave` (shuttle) →
  `lançadeira` (Demon ch. 64 ×2, Shadows ch. 81). English labels: Ashes nav `COVER` → `Capa`, `TITLE PAGE` → `Folha de rosto`,
  `COPYRIGHT PAGE` → `Direitos autorais`, `DEDICATION` → `Dedicação`, nav `Contents` → `Sumário`; Shadows nav `Contents` →
  `Sumário`; Disquiet nav `Table of Contents` and title `Contents` → `Sumário`. Kept on purpose: the Demon elenco braces `{ }` (in the
  source). Backups: `data/tmp/corrections-2026-11-14-backup/`. Deterministic audit: all pass except Ashes (the two false positives).
  Cloud re-judge: all pass with 0 meaning and 0 gender errors (about $0.008 total). The `telegrafou` verb form stays.
- **Gender fixes 2026-11-14 (owner approved):** Howling ch. 7 `num varanda` → `numa varanda`; Howling ch. 27 title
  `MEU ENCONTRO COM A oráculo` → `… COM O oráculo` (the article sits in a separate span); Shadows ch. 59 `dos nossos botas` →
  `das nossas botas`. Backups: `data/tmp/gender-fixes-2026-11-14-backup/` (Howling and Shadows, as they stood before this step).
  Deterministic audit passes for both; cloud re-judge passes with 0 meaning and 0 gender errors (about $0.0024 in total).
- **Queue agent** runs from the main checkout (`scripts/queue_runner_agent.py`).
  Queue changes from the UI need it; start `start-queue-agent.bat` if it is down.
- **Disquiet Gods (Sun Eater 6, book 9)** re-translated from the EPUB 3.0 library source
  (run 16:43 to 22:26 local, 2026-11-12). Job state `needs_review`: waiting for human review
  in the Queue UI. After the run its refined file was gated: progressive repair (33 pt-PT
  periphrases converted; the noun "mulher" left alone), EPUBCheck 0/0/0, pair validation
  passed, deterministic audit passed (cloud audit disabled). Matter fixes: English `<title>`
  elements in 002, 075 and 077, the series header in 002, "escolástico" to "escoliasta" in 007
  and "escritores" to "escoliastas" in 045. Backups: `data/tmp/disquiet-gods-pre-progressive-2026-11-12/`
  and `data/tmp/disquiet-gods-pre-matter-fix-2026-11-13/`. The old output came from the superseded
  EPUB 2.0 source (`data/tmp/disquiet-gods-superseded-2026-11-12/`). Book 9 keeps the EPUB 2.0
  hash in `books.source_hash`.
- **Shadows Upon Time (book 13) needs review.** Its queue run finished 2026-11-13 06:03 local and
  stopped at the review gate.
- **pt-BR model stage: done 2026-11-12 under a stricter rule.** The guard checked numbers and
  word counts only, and accepted "azul-celeste" to "azul-você", "esquecida" to "esquecido"
  and "que não existe" to "que não existia". `conversion_only` (`src/literary/ptbr_revise.py`)
  now accepts only second-person verbs and pronouns becoming their pt-BR forms, and "estar a"
  infinitives becoming gerunds. Replayed from the saved answers (temperature 0; no GPU). Replaced
  refined files: Demon 11, Howling 19, Kingdoms 14 paragraphs; backups `*.refined.pre-ptbr.epub`.
  Kindle folder rebuilt (Howling, Demon, Ashes). Kingdoms is ready for review.
- **Approved 2026-11-12:** Ashes of Man (book 7), `completed`. Kingdoms of Death (book 11) was
  reopened the same day as `needs_review` until its pt-BR model stage is done. The previous
  refined files are `*.refined.pre-review.epub`.
- **Sun Eater terms follow the official pt-BR edition** (Império do Silêncio): peoples and
  species in lower case (cielcin, mericanii, aeta, ...), titles mid-sentence in lower case
  (lorde, sir, imperador, comandante, ...). Books 2 to 5 were rewritten; the previous files
  are `*.pre-official-case.epub`.
- **pt-PT progressive ("estar a" + infinitive → "estar" + gerund):** `src/literary/progressive_repair.py`
  rewrites only the verbs listed in `PROGRESSIVE_GERUNDS` (nouns such as "dor" and "favor" are
  left alone). Applied to the refined files of Howling Dark, Demon in White, Kingdoms and
  Ashes (EPUBCheck 0 errors; backups in `data/tmp/progressive-repair-backup-2026-11-12/`).
  Kindle folder rebuilt. Wired into the queue run after the id repair (from this change on).
  The three leftovers were fixed by hand on 2026-11-12: "despregar" (Ashes, now "lançando"),
  and the two split by markup (Demon "estava</i> brincando", Ashes "estava <a/>gritando").
- **Kingdoms chapter 40 title** ("Que Altar Verde", literal for "What Green Altar"): kept
  (decided 2026-11-12). No official pt-BR chapter list was found online; the map in
  `literary-resources/.../chapter-titles/kingdoms-of-death.yaml` still marks it as editorial.
- **Glossary:** `eali` (Jaddian ruling caste) is `policy: keep` and approved (2026-11-12). The
  compiled Disquiet Gods glossary was rebuilt once, before that flag change.
- **Sun Eater pt-BR revision, word-swap stage: done 2026-11-12** on Demon, Howling and Kingdoms
  (guard, EPUBCheck 0, `validate_epub_pair` unchanged). Backups in
  `data/tmp/progressive-repair-backup-2026-11-12/pre-ptbr-swaps/`. The model stage (`tu`, second-person verbs, "estar a") is done for Demon, Howling and Kingdoms (see
  the bullet above).
- **Queued on Index:** Ship of Magic (2), Fool's Errand (4), Ship of Destiny (1),
  The Golden Fool (6), Fool's Fate (5). Their Hy-MT2 outputs are in
  `translated_files/archive-hy-mt2-2026-11-12/`.
- **Branches:** every local branch is merged or equivalent in `main`. Two
  remote copies of merged branches remain on `origin` (`fix/epub-contributor-role`,
  `fix/glossary-forbidden`); delete them on request.
- **UI pass (buttons, tabs, completed translations):** merged into `main` by fast-forward (2026-11-12, tip
  `4eae8b6`); not pushed. Verified on a test instance at 127.0.0.1:5055
  (queue DB copy in `data/ui-check/`, gitignored): tab ARIA and arrow/Home/End keys,
  light and dark, mobile wrap, history rows. Fixed 2026-11-12 at 375 px (checked in the
  browser on the live app): the tab row scrolls sideways instead of wrapping to three rows,
  the glossary table scrolls inside its container, card headers and the app header wrap
  instead of overflowing (the page no longer scrolls sideways). Rules are in the
  `max-width: 480px` block of `_ui-polish.scss` and `#glossaryListContainer` in `_editors.scss`.
  Open: one 400 on a model-list request at page load is not yet identified; the language
  and status pill text is tight at 375 px.

- **Front-end pass (2026-11-11, merged into `main`):** stylesheets are SCSS partials in `src/web/static/scss`,
  compiled with `npm run build:css` into `src/web/static/css/app.css`; spacing and radius
  tokens are in `_tokens.scss`. Mobile media queries are gone (desktop-first).
  **Deploy check done (2026-11-12):** the live page links only `/static/css/app.css`, and the five
  legacy stylesheets (`style.css`, `queue.css`, `ui-polish.css`, `literary-theme.css`,
  `theme-dark.css`) are not on disk. Nothing left to delete or restart.
  Not done: JS comment sweep beyond narration lines; TypeScript and HTML-generation decisions.

## Books

| Book | Queue | State | Notes |
| --- | --- | --- | --- |
| Ship of Magic (Realm, Liveship 1) | 2, completed | polished + standardized (2026-11-18) | `37` chapters in NCX, `pdftohtml`/Outline stripped, progressive + reader repair, `EPUBCheck 0/0/0`; in `translated_files/kindle/`. |
| The Mad Ship (Realm, Liveship 2) | 3, completed | polished + standardized (2026-11-18) | `41` NCX entries (`42` headings), Ch 35 split fixed, `EPUBCheck 0/0/0`; in `translated_files/kindle/`. |
| Ship of Destiny (Realm, Liveship 3) | 1, completed | polished + standardized (2026-11-18) | `42` chapters in NCX, Ch 17/18/20 + `&lt;/?KTRANSLATION&gt;` fixed, `EPUBCheck 0/0/0`; in `translated_files/kindle/`. |
| Sun Eater 2–7 (Howling Dark .. Shadows Upon Time) | 10, 8, 11, 7, 9, 13 | completed | All `6` exported in `translated_files/kindle/` (`10` total completed books with Lonesome Dove + Liveship 1–3). |
| Lonesome Dove | 32, completed | completed | Exported in `translated_files/kindle/`. |
| Fool's Errand (Realm, Tawny Man 1) | 4, translating (`job #41`, priority 20) | `gemini` / `gemini-3.8-flash` (`cli_93ddf44e`) | Fresh run from chunk `1/851` on `data/calibre/prepared/fool-s-errand.epub` (old Ollama `job #40` retired); estimated `$2.20`. |
| The Golden Fool, Fool's Fate | 6, 5 (priorities 19, 18) | pending (`gemini-3.8-flash`) | Sanitized under `data/calibre/prepared/` (`toc_r1` NCX `33` / `43`, `EPUBCheck 0/0/0`). |
| Fool's Assassin, Fool's Quest, Assassin's Fate | 16, 17, 18 (priorities 17..15) | pending (`gemini-3.8-flash`) | Sanitized under `data/calibre/prepared/` (`OPF-030` / `<img alt="">` fixed). |
| The Rain Wild Chronicles | 33, priority 14 | pending (`gemini-3.8-flash`) | Sanitized `data/calibre/prepared/the-rain-wild-chronicles.epub` (`order: 13`, `116` compiled terms). |
| Malice, A Time of Dread, A Little Hatred | 29, 30, 31 (priorities 13..11) | pending (`ollama` / Index-9B) | Sanitized under `data/calibre/prepared/` (`OPF-030` fixed). |
| Farseer trilogy (Assassin's Apprentice, Royal Assassin, Assassin's Quest) | not queued | reference EN/PT-BR pairs in Calibre & `data/editorial_samples/` | Canonical official PT-BR terms & style synced into `realm-of-the-elderlings/`. |
| Malazan | 19..28 (priorities 10..1) | pending | Zero glossary terms; inherits global `proper_nouns` and `brazilian_prose` style rules. |

## Procedures

**Re-queue a completed book.** `completed` has no outgoing transitions. Set
`books.status = 'pending'` (after a backup of `data/literary_queue.db`), set the
model with `queue set-model`, then check `queue plan --book-id N` (no issues).
Move the old EPUBs out of `translated_files/` first: a fresh run refuses to
overwrite an existing output. A resume only happens from `paused`/`interrupted`
with a resumable checkpoint.

**pt-BR revision of a finished Sun Eater EPUB** (`src/literary/ptbr_revise.py`).
1. Count: `python -m src.literary.ptbr_revise --dry-run --epub <refined> --out <tmp>`.
2. Run: same command without `--dry-run`, with `--report <json>` and
   `--model hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M`. Word swaps are
   applied directly; verbs and "tu" go to the model (about 20 s per call).
3. Gates on the output: `validate_epub_pair` against the English source,
   EPUBCheck 0 errors, and `audit_book.py --report <queue run report>` (the
   report points the audit at the refined file).
4. Read ten changed paragraphs against the English source. Only then replace
   the refined file; keep a `.pre-ptbr` backup.
Known limits: the model converts about half of the verb and "tu" cases; the
guard refuses unrequested changes; refused paragraphs stay European and are
listed in the report.

**Refine pass.** `refine-epub` pairs the source and the draft paragraph by
paragraph. Final reader-repaired files no longer pair (Howling: 0 of 94
documents). Do not re-run it on finals; see
`docs/project/reviews/local-model-ceiling-2026-11-12.md`.

## Gates and tooling

- Deterministic audit (`scripts/audit_book.py`): glossary coverage ≥ 0.90 overall
  and ≥ 0.80 per file, forbidden renderings 0, pt-PT ≤ 50/100k, English leakage
  ≤ 0.01, repetition ≤ 0.05, length ratio 0.80–1.20. Glossary matching ignores
  case (2026-11-12).
- Cloud audit needs an approved cap (`--max-cloud-usd`). No cloud spend now.
- Glossary eligibility (`per_file_audit._form_present`, 2026-11-12): single words match as whole
  words at any length. Before, `Raine` matched `drained` and `Scholiast` matched `scholiasts`, which
  made phantom pairs. Audits run before this fix may report different per-file counts.
- pt-BR checker (`src/literary/ptbr.py`) flags European Portuguese: `tu` with its
  verbs, `estar a` + infinitive, de facto, contacto, demónio, prémio, -ámos,
  convosco, teu/tua. Refine and the revision both use it.
- Reader repair terms and headings per book: `literary-resources/christopher-ruocchio/sun-eater/reader-repairs.yaml`.
  The resource loader reads any top-level `terms` key as glossary; do not use it.
- Post-passes: `src/literary/chapter_titles.py` (titles from the map; `--relabel`
  with `--titles` for translated titles), `src/literary/chapter_headings.py` (Ship
  aligner; not for files that already have headings).
- Front-end TypeScript: sources are `.ts` next to the modules they replace; `npm run build`
  emits the `.js` files the browser loads (no bundler, same ES module graph). Check with
  `npm run typecheck` (strict). Commit the generated `.js` with the `.ts`. Migrated so far:
  `translation/progress-title`. Next: `queue/queue-manager.js` (2,035 lines; strict run gives
  264 errors: ~100 untyped parameters, ~80 DOM property accesses on `HTMLElement`, 20 `catch`
  blocks with `unknown`). Then the rest of `translation/`.
- UI load baseline during a real run (Ashes, 2026-11-12, live page, 30-40 s windows):
  0 long tasks over 50 ms; 3.3 DOM mutations/s; 9-12 `/api/` requests per 30-40 s (queue,
  log, control, about every 10 s); API median 38-39 ms, one outlier 770-820 ms. After the
  `ui/html` helper in `renderSummary` and `renderEvents`: unchanged. Rule: no new polling;
  re-measure with the same script before changing render paths in `queue-manager`.
- Targeted repair (merged from `feat/chunk-quality-gates`; not wired into the pipeline): `src/literary/targeted_fix.py`
  repairs paragraphs of a finished EPUB that carry a forbidden glossary form or a blocking pt-PT
  form. Model call only for flagged paragraphs; accepted only when the failure is gone and the
  guard passes. Howling Dark (refined): 12 of 7,650 paragraphs flagged, 5 of them with inline
  markup (skipped). Run on a copy of the refined book (2026-11-12, guard v2, commit 235f908):
  7 attempted, 6 accepted, 1 rejected ("pagar" -> "construindo", a meaning error the v1 guard
  let through). Remaining flagged: 6, all in paragraphs with inline markup or the rejected one.
  No XHTML broke. Decided 2026-11-12: the six accepted changes are pt-BR word swaps (contacto,
  demónio, facto, prémio, Podia) and are now in the refined Howling file. The module stays out of
  the pipeline: it needs the model per paragraph, and its one trial rejection was a meaning error.
- Container `translatebook-literary-dev` (127.0.0.1:5000) mounts `src` read-only:
  restart it to load Python changes; no rebuild needed.
- Tests: `venv\Scripts\python.exe -m pytest -q tests/unit tests/literary tests/test_frontend_i18n.py`.
  `tests/unit/conftest.py` points `LITERARY_QUEUE_DB` at an empty file per test, so the
  translate routes no longer see the live queue: 2226 pass in `tests/unit` with a translation running.

## Queue runtime

- **Never restart the app container while a translation runs.** The runner executes
  the translation through a `docker compose exec` it owns on the host; a container
  restart closes that exec and the job dies with exit 137 (seen three times on
  2026-11-11 at 22:51, 22:59 and 23:26). Wait for the job to stop, or pause it first.

- Single writer: the app spools each change to `data/literary_queue.intents/`;
  the host agent applies them in order (every 0.5 s, also during a run). Design:
  `docs/project/reviews/single-writer-design-2026-11-11.md`.
- Live jobs DB: named volume `/app/state/jobs.db`; host mirror `data/jobs.mirror.db`.
  Journal mode DELETE (no WAL on the bind mount).
- Known defects: a job can stay `running` after a complete resume (not reproduced,
  see decision 6); the watchdog is monitor-only; UI reads still cross the bind
  mount (design §9).

## Open decisions

1. **Resolved 2026-11-12.** Kingdoms chapter 15: derived forms of a glossary target are data (`accepted_targets`; Legião accepts legionário(s)); `Sollan` used as an adjective is now sollana/sollano. The audit passes.
2. **Meaning gate (Howling).** Resolved 2026-11-12: Howling was approved by hand in the
   Queue UI and the gate is unchanged. Option 5 of `adjudicator-calibration-2026-11-11.md`
   (human review on any confirmed candidate) stays the recommendation; it needs a blind run first.
3. **Imperium vs Império.** The freeze is merged; Demon and Howling keep
   "Império" by owner decision.
4. **Resolved 2026-11-12.** The per-book rules are data now (`reader-repairs.yaml`:
   `book_text_fixes`, `labels`, `reader_terms`; `running_header` in the Ship of Magic spec;
   `forbidden_forms` metric). Still in code by design: the copyright lines and the Sun Eater
   series gate in `polish.py`.
5. **Owner confirmations:** the "Scriptorium" name; upstream issue #333 is open.
6. **Resume duplicate `(1)`: fixed 2026-11-12.** `translate.py` applied a free name even on a
   `--translation-id` resume, so the partial output got a stale copy. `resolve_output_path`
   (`src/utils/file_utils.py`) keeps the path on a resume. Tests: `tests/unit/test_output_path_resume.py`.
   Not reproduced: a job left `running` after a complete resume. It needs a live case to trace.
7. **Watchdog: keep monitor-only.** Killing a translation from the watchdog is destructive
   (a container restart already kills the job with exit 137). Monitoring is enough for now.
8. **Queue UI reads across the bind mount (design §9): deferred.** No user-visible failure
   recorded; it is an architecture change.
9. **Resolved 2026-11-15 (Disquiet Gods description).** Supplied a curated PT-BR
   back-cover synopsis for *Disquiet Gods* in `src/literary/metadata.py` (`_CURATED_DESCRIPTIONS_PTBR`),
   matching `sun-eater/worldbuilding.yaml` terminology (`os Quietos`, `Vigilantes`,
   `Imperador Sollano`, `cielcin pálidos`, `HAPSIS`, `Jadd`, `Cassandra`), and embedded it
   into `Disquiet Gods (pt-BR).refined.epub` and `translated_files/kindle/`. The
   pipeline's 4,000-character translation limit remains unchanged for new translations.
10. **Malazan glossary: not queued.** Building it means deciding pt-BR policy for hundreds of
    invented names; it needs the owner's naming decisions first.
11. **24 h destructive test: blocked** until the queue is idle and the dedicated app is up.
    Run it after Disquiet Gods and the model stage of the Sun Eater revision.

## Model policy and evidence

- **Gemini 3.8 Flash (`gemini` / `gemini-3.8-flash`, `thinkingBudget: 0`) for active *Realm of the Elderlings* queue (`#4, #6, #5, #16..#18, #33`):** funded by `US$ 40` Google Developer Program monthly credit + `R$ 30` Prepay wallet top-up on `GEMINI_API_KEY`; live Hobb verification scored `100%` `name_recall` and `$13.02 / 1M` words (`docs/project/reviews/hobb-gemini-pilot-2026-11-18.md`).
- Local `Index-Translate-9B` remains default for completed *Sun Eater* / *Liveship Traders* and later non-Hobb series (`Malazan`, `Gwynne`, `Abercrombie`). Evidence:
  `docs/project/reviews/sun-eater-model-selection-2026-11-10.md`,
  `docs/project/reviews/local-model-benchmark-2026-11-10.md`,
  `docs/project/reviews/local-model-ceiling-2026-11-12.md`.
- Balances / Caps (`data/budgets.json`): Gemini `cap_usd: 45.0` (snapshot `2026-11-18`), Anthropic `US$ 1.54`, DeepSeek `US$ 1.38` (snapshot `2026-11-10`). Ledger: `data/cost_ledger.jsonl`.

## Repository

- Branch `main`. Keep untracked user files out of commits (`.taste-skill/`,
  `Custom_Instructions/sun-eater-2.yaml`).
- Product name is Scriptorium; upstream credits, `tbl-*` EPUB ids, localStorage
  keys and `TBL_*` variables stay on purpose.
- Prompt library status: `docs/prompts/README.md` (top block).
