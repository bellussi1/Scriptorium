# Environment and Calibre inventory

Checked on **2026-11-07** on the user's Windows machine. This is a factual
snapshot, not an assumption about what is installed.

## 1. Hardware

| Item | Value |
|---|---|
| CPU | AMD Ryzen 5 5500, 6 cores / 12 threads, 3.6 GHz base |
| RAM | 31.9 GB usable |
| GPU | NVIDIA GeForce RTX 4060, 8,188 MiB VRAM |
| Driver | 610.88 (CUDA UMD 13.3) |
| Disk | C: 720.7 GB used, 232.2 GB free |
| OS | Windows 11 Home, 10.0.26200, 64-bit |

The desktop was already using ~1.2 GB of VRAM when measured, leaving roughly
6.7 GB free. This matters for the 8 GB card: a Q4 model whose weights are
8.1 GB does not fit and will offload.

## 2. Software

| Tool | Version / state |
|---|---|
| Docker Desktop | 29.8.2 |
| Docker Compose | v5.5.1 |
| WSL2 | `docker-desktop`, running, version 2 |
| GPU in container | Confirmed: `nvidia-smi` sees the RTX 4060 inside a CUDA container |
| Ollama | 0.40.15, running on the host |
| Python (system) | 3.14.2 |
| Git | 2.49.0.windows.1 |
| Calibre | 9.1 (`calibredb`, `ebook-convert`) |
| Java | 1.8.0_441 only; EPUBCheck 5.x needs a newer JDK, so EPUBCheck is **not** available yet |
| Project venv | Broken: it points to a removed uv Python 3.12.15. Do not rely on it; use Docker. |

### Installed Ollama models

| Model | Size | Notes |
|---|---:|---|
| `translategemma:12b` | 8.1 GB | Q4_K_M Gemma 3 12B translation model; fixed prompt; ~2K-token training regime |
| `translategemma:12b-it-q4_K_M` | 8.1 GB | Same blob as above |
| `qwen3:14b` | 9.3 GB | Generalist; will offload on 8 GB VRAM |
| `qwen3:8b` / `qwen3:8b-q4_K_M` | 5.2 GB | Generalist; fits with a modest context |
| `qwen3.5:4b` | 3.4 GB | Fast smoke-test model |
| `gemini-3-flash-preview:latest` | — | Local wrapper/alias, not a cloud credential |
| `hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M` | 4.6 GB | Official Apache-2.0 translation model; 9.6 GB runtime at 8K on this card; strongest terminology result so far |
| `hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M` | 6.4 GB | Official Apache-2.0 model plus 0.62 GB vision projector; 7.4 GB runtime at 8K; faster draft engine |

`ollama list` reports nine entries because the two TranslateGemma tags share a
blob, `qwen3:8b` and `qwen3:8b-q4_K_M` share another, and the Index entry
includes the multimodal projector.

### Docker networking

The app container reaches host Ollama at
`http://host.docker.internal:11434/api/generate` through
`extra_hosts: host.docker.internal:host-gateway`. This was tested end to end:
the app started, `/api/health` returned 200, and it listed all seven Ollama
models.

### Why Ollama is not containerized

The GPU is visible in containers, so it *could* run in one. It is kept on the
host because the host already has the correct Windows CUDA driver and the
model cache; containerizing it would add a second GPU runtime, a second model
store and a `host.docker.internal` hop without improving quality. The
application container does not need GPU access. This is the simpler correct
architecture for this machine.

## 3. Repository state

| Item | Value |
|---|---|
| Local branch | `main` |
| HEAD | `b5ed606` — upstream release **1.5.22** |
| Upstream | `hydropix/TranslateBooksWithLLMs` |
| Fork remote | `bellussi1/TranslateBooksWithLLMs` |
| Local vs upstream | Fast-forwarded to upstream `main`; 45 commits behind was the starting state |
| Local changes | Additive literary layer, dev Docker files, two small glossary patches, tests; no push |
| Python version in image | 3.11-slim (the upstream Dockerfile uses 3.11) |

The new development image builds from **local source**, not from the published
GHCR image. The original `docker-compose.yml` still points at the published
image; `docker-compose.dev.yml` is the editable build.

## 4. Calibre library

Library root: `C:\Users\Bellussi\Biblioteca do calibre` (read-only).

The database was opened with SQLite `mode=ro` and `PRAGMA query_only = ON`.
No metadata, cover, EPUB or `metadata.db` was written. `calibredb` was not used
for the inventory because the read-only SQLite path is easier to audit.

### Overall inventory (metadata only, all 220 records)

| Metric | Value |
|---|---:|
| Books | 220 |
| Authors | 72 |
| Series | 44 |
| EPUB records | 220 |
| Target records scanned (McMurtry/Hobb/Ruocchio) | 28 |
| Target words (all editions) | 7,696,672 |

The full metadata inventory is at `data/calibre/library_metadata.json`; the
target EPUB scan is at `data/calibre/targets.json`. Both are gitignored.

### Target authors and series

| Author | Work / series | Records | Languages | Notes |
|---|---|---:|---|---|
| Larry McMurtry | Lonesome Dove | 2 | EN + PT draft | EN Calibre 311; the PT file (Calibre 405) is the user's own **unreviewed draft**, not an official edition and not a gold reference. Duplicate title/author pair, not a duplicate edition. |
| Robin Hobb | The Farseer Trilogy | 6 | EN + PT (3 each) | Both editions for all three volumes. |
| Robin Hobb | The Liveship Traders | 3 | EN | No PT in the library. |
| Robin Hobb | The Tawny Man Trilogy | 3 | EN | No PT in the library. |
| Robin Hobb | The Rain Wild Chronicles | 1 | EN | One omnibus containing four novels (Calibre 331). **Deferred by the user; not in the active queue.** If revisited, split before per-novel queueing. |
| Robin Hobb | The Fitz and the Fool Trilogy | 3 | EN | No PT in the library. |
| Christopher Ruocchio | Sun Eater main novels | 7 | EN (6) + PT (1) | Book 1 is the official PT `Império do Silêncio` (Calibre 436); books 2–7 are EN. |
| Christopher Ruocchio | Sun Eater novellas | 3 | EN | The Lesser Devil (1.5), Queen Amid Ashes (2.5), The Dregs of Empire (5.5). |

### Word counts (measured from the EPUB text)

| Work | Words | Chapters / docs | Calibre |
|---|---:|---:|---|
| Lonesome Dove EN | 365,575 | 109 | 311 |
| Lonesome Dove PT draft (user's, unreviewed) | 353,609 | 109 | 405 |
| Assassin's Apprentice EN | 165,049 | 35 | 336 |
| Assassin's Apprentice PT | 163,924 | 33 | 94 |
| Royal Assassin EN | 260,533 | 39 | 329 |
| Royal Assassin PT | 257,065 | 40 | 92 |
| Assassin's Quest EN | 345,928 | 52 spine docs | 338 |
| Assassin's Quest PT | 326,417 | 48 | 71 |
| Ship of Magic | 329,502 | 1 TOC label / spine count | 332 |
| The Mad Ship | 317,430 | — | 339 |
| Ship of Destiny | 312,426 | — | 340 |
| Fool's Errand | 239,098 | — | 334 |
| The Golden Fool | 255,095 | — | 328 |
| Fool's Fate | 325,664 | — | 337 |
| The Rain Wild Chronicles (omnibus) | 672,555 | 107 | 331 |
| Fool's Assassin | 257,743 | — | 335 |
| Fool's Quest | 293,171 | — | 330 |
| Assassin's Fate | 358,021 | — | 333 |
| Sun Eater 2 — Howling Dark | 264,961 | 91 | 430 |
| Sun Eater 3 — Demon in White | 295,868 | 97 | 431 |
| Sun Eater 4 — Kingdoms of Death | 208,702 | 61 | 432 |
| Sun Eater 5 — Ashes of Man | 209,648 | 56 | 433 |
| Sun Eater 6 — Disquiet Gods | 287,252 | 72 | 434 |
| Sun Eater 7 — Shadows Upon Time | 379,064 | 100 | 435 |
| Sun Eater 1 PT — Império do Silêncio | 262,601 | 90 | 436 |
| The Lesser Devil | 58,058 | — | 295 |
| Queen Amid Ashes | 49,537 | — | 296 |
| The Dregs of Empire | 82,176 | 19 | 297 |

Some chapter counts are 1 because the EPUB has a single navigation label even
though the spine has many documents. The inventory reports both
`chapter_count` and `document_count`; use the spine count for progress and the
TOC count for user-facing chapters.

### Metadata and structural issues found

1. **Calibre metadata was standardized on 2026-11-07.** `calibredb
   set_metadata` updated 28 records for McMurtry, Hobb and Ruocchio: Sun Eater
   main novels 2–7 now carry `The Sun Eater` and indices 2–7; the PT book 1
   title is `Império do Silêncio`. The plans remain committed in each
   `metadata.yaml`; the before/after report is
   `data/calibre/metadata-apply-report.json` and the backup is
   `data/calibre/backup/metadata-20261107-200323.db`. Direct SQL writes to
   `metadata.db` remain forbidden.
2. **Lonesome Dove PT was renamed `Pombo Solitário` and its `author_sort`
   changed from `Unknown` to `McMurtry, Larry`.** The file is still the user's
   unreviewed translation, not an official edition; it must not be used as a
   reference for terminology or style without revision. The EPUB's internal
   `dc:title` remains `Lonesome Dove`, so the inventory reports a known
   informational mismatch.
3. **Farseer EN/PT pairs look like duplicates to a naive title/author check.**
   They are bilingual pairs. The inventory now classifies same-language copies
   as duplicates and different-language copies as `[info] Bilingual pair`.
4. **EPUB language tags differ from Calibre codes.** Calibre uses `por`, EPUBs
   use `pt` or `pt-BR`; the inventory normalizes ISO 639-1/2 codes before
   comparing.
5. **The Rain Wild omnibus is one EPUB for four novels.** It is deferred by the
   user and is not in the active queue. If it is revisited, split it at the four
   book boundaries before a per-novel queue; the current inventory sees one
   672,555-word book.
6. **The Sun Eater PT edition has a future-looking Calibre pubdate
   (2026-11-15) and an ASIN identifier.** Verify the edition and publication
   date before using it as a style/terminology reference; the text itself is
   usable.
7. **No official PT editions were found for Liveship Traders, Tawny Man, Rain
   Wild or Fitz and the Fool.** Do not invent their terminology. The style
   profiles for those subseries are explicitly provisional.

### Series order used by the roadmap

- **Realm of the Elderlings:** Farseer (1–3) → Liveship Traders (4–6) → Tawny
  Man (7–9) → Fitz and the Fool (14–16). Rain Wild (10–13) is deferred and is
  **not** in the current priority order. Publication order is the default
  translation and reading order. The optional novella *The Willful Princess and
  the Piebald Prince* is not in the library.
- **Sun Eater:** main novels 1–7; novellas 1.5, 2.5 and 5.5. The novellas are
  complementary, not prerequisites. Book 1 already exists in PT; the translation
  queue starts at book 2.
- **Lonesome Dove:** treat as standalone first. Related books are *Streets of
  Laredo* (sequel, 1993), *Dead Man's Walk* (prequel, 1995) and *Comanche Moon*
  (prequel, 1997); none are in the library. Do not queue them without files.

## 5. Reproducibility notes

- The app image is built by `docker-compose.dev.yml` from
  `deployment/Dockerfile.dev`.
- The Calibre mount is read-only: `${CALIBRE_LIBRARY_PATH}:/library:ro`.
- The app is bound to `127.0.0.1:5000`, not all interfaces.
- `data/`, `translated_files/` and `logs/` are persistent bind mounts.
- The container runs as UID 1000, drops capabilities, sets
  `no-new-privileges`, and uses a read-only root filesystem with `/tmp` as
  tmpfs.
- Python bytecode is disabled so the read-only `src` mount is safe.
- `PYTHONPATH=/app:/app/src` is set so both `src.*` imports and the legacy
  `prompts.*` imports used by upstream tests resolve.
