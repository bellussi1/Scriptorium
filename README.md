
https://github.com/user-attachments/assets/4afc5f90-18d8-4586-ba73-626ae681ba57
<div align="center">
  <h1>Scriptorium</h1>
  <p><strong>Tradução literária EN → pt-BR</strong> — fork pessoal de <a href="https://github.com/hydropix/TranslateBooksWithLLMs">TranslateBooksWithLLMs</a> (AGPL-3.0).</p>
</div>

A local-first literary translation pipeline for **English → Brazilian Portuguese**. It runs one book at a time, keeps a glossary and a style per series, resumes from checkpoints, and produces a validated EPUB for KOReader/Calibre. There are no published binaries or images for this fork; build it from this checkout.

> **Fork scope:** this checkout's browser UI and `/api/translate` are fixed to
> **English -> Brazilian Portuguese**. The generic translator code remains in the
> repository, but other pairs are not exposed by this fork.

**Formats:** EPUB, SRT, DOCX, PDF, TXT

- **No size limit.** Process documents of any length - from a single page to thousand-page novels. The intelligent chunking system handles unlimited content while preserving context between segments.
- **Perfect preservation.** Your documents come out exactly as they went in: EPUB formatting, styles, and structure remain intact. SRT timecodes stay perfectly synchronized. Every tag, every timestamp, every formatting detail is preserved.
- **Resume anytime.** Interrupted translation? Pick up exactly where you left off. The checkpoint system saves progress automatically.
- **Reusable writing styles.** Extract a style preset from sample books (or write one by hand) and apply it to every chunk for a consistent register, rhythm, and imagery across the whole translation.
- **Auto glossary & style.** No glossary or preset ready? Pick Auto in the dropdown and the app derives both straight from the document being translated - one extra LLM call each before the job starts, nothing saved.
- **PDF support.** Text PDFs are translated into a new, reflowed PDF: headings, paragraphs, lists and images are kept, ruled tables are rebuilt as tables, and paragraph colours, background boxes and the font family (serif, sans-serif, monospace) are preserved, but the original page layout is not, and bold or colour inside a sentence is not. Scanned PDFs are not supported (no OCR), multi-column layouts are best effort, and the refinement pass is not available for PDF yet.

<img width="1150" height="579" alt="image" src="https://github.com/user-attachments/assets/d7dfa806-830b-4405-8300-f10208943d22" />

---

## Quick Start (local build)

This fork is built from this checkout. It does not publish desktop binaries or
a prebuilt Docker image.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and
   [Ollama](https://ollama.com/), then pull a model: `ollama pull qwen3:14b`.
2. Clone this fork and create the environment file:
   ```bash
   git clone https://github.com/bellussi1/TranslateBooksWithLLMs.git
   cd TranslateBooksWithLLMs
   cp .env.example .env        # macOS/Linux
   Copy-Item .env.example .env # Windows PowerShell
   ```
3. Set `CALIBRE_LIBRARY_PATH` to your Calibre library and `DEFAULT_MODEL` to the
   model you pulled. The dev compose reads `.env` and mounts the library at
   `/library`.
4. Build and start the local container:
   ```bash
   docker compose -f docker-compose.dev.yml up -d --build
   ```
5. Open http://localhost:5000.

The container writes EPUBs to `translated_files/` and keeps the live jobs DB in
the `jobs_state` volume. See [docs/DOCKER.md](docs/DOCKER.md) for the CLI, the
queue agent and the source-only setup.

---

## Providers

<p align="center">
<a href="https://ollama.com/"><img src="src/web/static/img/providers/ollama.png" alt="Ollama" height="32"></a>&nbsp;&nbsp;
<a href="https://poe.com/"><img src="src/web/static/img/providers/poe.png" alt="Poe" height="32"></a>&nbsp;&nbsp;
<a href="https://openrouter.ai/"><img src="src/web/static/img/providers/openrouter.png" alt="OpenRouter" height="32"></a>&nbsp;&nbsp;
<a href="https://openai.com/"><img src="src/web/static/img/providers/openai.png" alt="OpenAI" height="32"></a>&nbsp;&nbsp;
<a href="https://mistral.ai/"><img src="src/web/static/img/providers/mistral.png" alt="Mistral" height="32"></a>&nbsp;&nbsp;
<a href="https://www.deepseek.com/"><img src="src/web/static/img/providers/deepseek.png" alt="DeepSeek" height="32"></a>&nbsp;&nbsp;
<a href="https://deepmind.google/technologies/gemini/"><img src="src/web/static/img/providers/gemini.png" alt="Gemini" height="32"></a>&nbsp;&nbsp;
<a href="https://build.nvidia.com/"><img src="src/web/static/img/providers/nvidia.png" alt="NVIDIA NIM" height="32"></a>
</p>

| Provider | Type | Get started |
|----------|------|-------------|
| **DeepSeek** | Cloud | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| **Gemini** | Cloud | [Google AI Studio](https://aistudio.google.com/apikey) |
| **Mistral** | Cloud | [console.mistral.ai](https://console.mistral.ai/api-keys) |
| **NVIDIA NIM** | Cloud | [build.nvidia.com](https://build.nvidia.com/) |
| **Ollama** | Local | [ollama.com](https://ollama.com/) |
| **OpenAI** | Cloud | [platform.openai.com](https://platform.openai.com/api-keys) |
| **OpenAI-Compatible** | Local or hosted (llama.cpp, LM Studio, vLLM, LocalAI...) | Point to your server's endpoint |
| **OpenRouter** | Cloud (200+ models) | [openrouter.ai/keys](https://openrouter.ai/keys) |
| **Poe** | Cloud (multi-model) | [poe.com/api_key](https://poe.com/api_key) |

See [docs/PROVIDERS.md](docs/PROVIDERS.md) for detailed setup instructions.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Ollama won't connect | Check Ollama is running, test `curl http://localhost:11434/api/tags` |
| Model not found | Run `ollama list`, then `ollama pull model-name` |

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for more solutions.

---

## Advanced

<details>
<summary><b>Run from source without Docker</b></summary>

**Prerequisites:** Python 3.11, [Ollama](https://ollama.com/), Git.

```bash
git clone https://github.com/bellussi1/TranslateBooksWithLLMs.git
cd TranslateBooksWithLLMs
python -m venv venv
.\venv\Scripts\activate      # Windows PowerShell
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
ollama pull qwen3:14b
python launcher.py           # starts the web server
# or: python translation_api.py
```

The web interface opens at **http://localhost:5000**. For the CLI, keep the
venv active and run `python translate.py --help`.

</details>

<details>
<summary><b>Command line</b></summary>

The browser UI is fixed to English → Brazilian Portuguese. The CLI accepts the
standard flags; use the same pair for consistency with the queue and glossary.

```bash
# Host, with the venv active and Ollama running
python translate.py -i book.epub \
  -sl English -tl "Portuguese (Brazil)" \
  --provider ollama -m qwen3:14b

# Inside the dev container, with the book under /library
docker compose -f docker-compose.dev.yml exec -T app python translate.py \
  -i /library/Author/Book/Book.epub \
  -o /app/translated_files/Book.pt-BR.epub \
  -sl English -tl "Portuguese (Brazil)" \
  --provider ollama -m qwen3:14b
```

The output defaults to `{name} (Portuguese (Brazil)).epub`; `-o` is optional.
The queue adds glossary, style and the review gate; see
`docs/project/README.md`.

### Main options

| Option | Description | Default |
|--------|-------------|---------|
| `-i, --input` | Input file | Required |
| `-o, --output` | Output file | Auto: `{name} ({lang}).{ext}` |
| `-sl, --source_lang` | Source language | English |
| `-tl, --target_lang` | Target language | Portuguese (Brazil) |
| `-m, --model` | Model name | qwen3:14b |
| `--provider` | ollama/openrouter/openai/gemini/mistral/deepseek/poe/nim | ollama |
| `--parallel` | Chunks translated concurrently (cloud only; Ollama stays at 1) | 1 |
| `--text-cleanup` | OCR/typographic cleanup | disabled |
| `--refine` | Second pass for literary polish | disabled |
| `--tts` | Generate audio (Edge-TTS) | disabled |

See [docs/CLI.md](docs/CLI.md) for all options (TTS voices, rates, formats, etc.).

</details>

<details>
<summary><b>Configuration (.env)</b></summary>

Copy `.env.example` to `.env` and edit:

```bash
# Provider
LLM_PROVIDER=ollama

# Ollama
API_ENDPOINT=http://localhost:11434/api/generate
DEFAULT_MODEL=qwen3:14b

# API Keys (if using cloud providers)
OPENROUTER_API_KEY=sk-or-v1-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
MISTRAL_API_KEY=...
DEEPSEEK_API_KEY=...
POE_API_KEY=...
NIM_API_KEY=...

# Performance
REQUEST_TIMEOUT=900
MAX_TOKENS_PER_CHUNK=450     # Token-based chunking (default: 450 tokens)
PARALLEL_TRANSLATIONS=1      # Concurrent chunks (cloud only; Ollama stays at 1)
```

**Faster on cloud providers?** Set `PARALLEL_TRANSLATIONS` (or `--parallel N`, or the "Parallel requests" field in the web UI) above 1 to translate several chunks at once. Local providers (Ollama) ignore it since a single instance serializes requests. Higher values are faster but can hit provider rate limits.

**Multiple API keys?** Any `*_API_KEY` variable accepts a comma-separated list (e.g. `GEMINI_API_KEY=key1,key2,key3`). The system rotates between keys automatically when one hits a rate limit - useful to chain free-tier accounts. See [docs/API_KEY_ROTATION.md](docs/API_KEY_ROTATION.md).

**Long jobs?** Get a push notification on your phone (via ntfy), Discord, Slack, gotify, or any HTTP endpoint when a translation finishes. Set `NOTIFY_WEBHOOK_URL` in `.env`. See [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md).

</details>

<details>
<summary><b>Docker (local build)</b></summary>

```bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml ps
docker compose -f docker-compose.dev.yml logs -f app
```

The dev compose builds `translatebook-literary:dev` from
`deployment/Dockerfile.dev`, mounts this checkout, and exposes
`127.0.0.1:5000`. This fork has no published image; do not pull the upstream
`ghcr.io` image. See [docs/DOCKER.md](docs/DOCKER.md) for the full local-build
guide, the CLI and the queue agent.

</details>

### Using the web UI from several devices

One server is one shared workspace - there are no user accounts, so every browser pointed at it sees the same state. A running job's progress panel, paused/interrupted jobs, the completed translation history, and the files in `translated_files/` are all shared: another device picks them up live (within a second or two) or on page load. A small set of preferences - TTS, text cleanup, bilingual mode, plain-text mode, and the selected custom instruction - is synced too: the server wins at page load, the last change wins after that, and a tab that is already open picks up changes made elsewhere on its next reload.

Two things stay local to the device: if you queue several files, other devices only see the one currently translating, not the rest of the queue (it's held in the browser that built it); and the UI language is per-browser. Provider, model, API keys, and endpoints are never synced - they always come from the server's `.env`.

---

## Documentation

| Guide | Description |
|-------|-------------|
| [docs/project/README.md](docs/project/README.md) | **Literary fork:** audit, model research, architecture, cost model and proof of concept |
| [docs/PROVIDERS.md](docs/PROVIDERS.md) | Detailed provider setup (Ollama, LM Studio, OpenRouter, OpenAI, Gemini) |
| [docs/API_KEY_ROTATION.md](docs/API_KEY_ROTATION.md) | Use multiple API keys per provider with automatic failover on rate-limit |
| [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md) | Webhook notifications on completion (ntfy, gotify, Discord, Slack, custom) |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Force consistent term translations across a book (Web UI + CLI, auto-extract via NER) |
| [docs/TERM_FIX.md](docs/TERM_FIX.md) | Fix a term in an already-translated book without translating again (Web UI + CLI) |
| [docs/STYLE_EXTRACTION.md](docs/STYLE_EXTRACTION.md) | Extract a reusable writing-style preset from sample books and apply it to every chunk (Web UI) |
| [docs/CLI.md](docs/CLI.md) | Complete CLI reference |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Problem solutions |
| [docs/DOCKER.md](docs/DOCKER.md) | Local Docker build guide |

---

## Upstream

This fork is based on [TranslateBooksWithLLMs](https://github.com/hydropix/TranslateBooksWithLLMs)
by hydropix and remains **AGPL-3.0**. The upstream repository, documentation
and model benchmarks are the reference for the code this fork builds on:

- [Upstream repository](https://github.com/hydropix/TranslateBooksWithLLMs)
- [Upstream model benchmarks](https://github.com/hydropix/TranslateBooksWithLLMs/wiki)

The original author's support link is preserved:
[Ko-fi](https://ko-fi.com/Y1M021FYBG).

---

**License:** AGPL-3.0
