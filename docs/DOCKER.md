# Docker — local build

This fork is **built from this checkout**. It does not publish a Docker image,
a desktop release or a package. The upstream `ghcr.io/hydropix/...` image is not
used here.

The local stack is `docker-compose.dev.yml`:

- service `app`
- image `translatebook-literary:dev`
- container `translatebook-literary-dev`
- Dockerfile `deployment/Dockerfile.dev`
- port `127.0.0.1:5000`

## Prerequisites

- Docker Desktop (Windows/macOS) or Docker Engine + Compose v2 (Linux)
- Ollama running on the host, with the model you intend to use
- A Calibre library on the host
- This repository checked out locally

## 1. Configure `.env`

```bash
cp .env.example .env        # macOS/Linux
Copy-Item .env.example .env # Windows PowerShell
```

Set at least:

```env
LLM_PROVIDER=ollama
DEFAULT_MODEL=qwen3:14b
CALIBRE_LIBRARY_PATH=C:/Users/you/Biblioteca do calibre
```

`CALIBRE_LIBRARY_PATH` is the host path mounted read-only at `/library` in the
container. The dev compose pins Ollama to
`http://host.docker.internal:11434/api/generate`; edit that line in
`docker-compose.dev.yml` if Ollama runs on another machine.

## 2. Build and start

```bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml ps
docker compose -f docker-compose.dev.yml logs -f app
```

The healthcheck calls `http://localhost:5000/api/health`. Open
**http://localhost:5000**.

The first build compiles the image locally. Nothing is pushed to a registry.

## 3. Translate from the CLI

Inside the running container:

```bash
# Check the CLI
docker compose -f docker-compose.dev.yml exec -T app python translate.py --help

# Translate a book from the mounted Calibre library
docker compose -f docker-compose.dev.yml exec -T app python translate.py \
  -i "/library/Author/Book/Book.epub" \
  -o "/app/translated_files/Book.pt-BR.epub" \
  -sl English -tl "Portuguese (Brazil)" \
  --provider ollama -m qwen3:14b
```

From the host, with the venv active and dependencies installed:

```bash
python translate.py -i book.epub \
  -sl English -tl "Portuguese (Brazil)" \
  --provider ollama -m qwen3:14b
```

The fork's queue path adds the glossary, style and review gate; see
`docs/project/README.md`.

## 4. Run the queue agent

The browser queue and the literary runner are separate. The app shows the
queue, but the host agent starts the actual `queue run-all` process:

```bat
start-queue-agent.bat
```

or, from a Python environment with the repo dependencies:

```bash
python scripts/queue_runner_agent.py
```

The agent calls `docker compose -f docker-compose.dev.yml exec ...` for the
translation process, so the dev container must be running. Keep one agent and
one book at a time.

## 5. Source-only setup (without Docker)

Prerequisites: Python 3.11, Ollama, Git.

```bash
python -m venv venv
.\venv\Scripts\activate      # Windows PowerShell
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
python launcher.py           # starts the web server
# or: python translation_api.py
```

`launcher.py` is the source/PyInstaller wrapper; from a source checkout it
prints `[DEV] Running as Python script` and starts the same Flask server.
The CLI is `python translate.py --help`.

## 6. Data and persistence

| Host path | Container path | Purpose |
| --- | --- | --- |
| `translated_files/` | `/app/translated_files` | translated EPUBs and Kindle exports |
| `data/` | `/app/data` | uploads, mirror, glossaries, snapshots |
| `logs/` | `/app/logs` | app logs |
| `jobs_state` volume | `/app/state` | live `jobs.db`; do not delete |

The live jobs DB lives on the Docker named volume. The host reads the mirror at
`data/jobs.mirror.db`; do not point the app at the mirror.

## 7. Update

```bash
git pull --ff-only
docker compose -f docker-compose.dev.yml up -d --build
```

No image, release or package is published by this fork. The update is always
from the checkout.

## 8. Tests

```bash
docker compose -f docker-compose.dev.yml exec -T app python -m pytest -q tests/unit tests/literary
docker compose -f docker-compose.dev.yml exec -T app python -m pytest -q tests/test_frontend_i18n.py
```

## Troubleshooting

- **Port 5000 busy:** stop the other app or change the port mapping in
  `docker-compose.dev.yml`.
- **Ollama connection refused:** check `ollama list` on the host; from the
  container, `host.docker.internal` must resolve.
- **Calibre library empty:** verify `CALIBRE_LIBRARY_PATH` in `.env` and the
  `/library` mount.
- **Healthcheck fails:** `docker compose -f docker-compose.dev.yml logs app`.
- **Permission errors on `data/` or `translated_files/`:** the container runs
  with a read-only root; those two paths must be writable by the container
  user.

## Upstream and license

This fork is based on
[TranslateBooksWithLLMs](https://github.com/hydropix/TranslateBooksWithLLMs)
by hydropix and remains **AGPL-3.0**. See `LICENSE` and the upstream
repository for the original project.
