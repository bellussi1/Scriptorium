# AGENTS.md

Project instructions for coding agents. Read `docs/ACTIVE_CONTEXT.md` before
starting and update it when you stop.

## What this checkout is

Scriptorium, a fork of [TranslateBooksWithLLMs](https://github.com/hydropix/TranslateBooksWithLLMs)
turned into a personal literary translation pipeline, **English → Brazilian
Portuguese only**. It exists for the owner's own reading: it is not a product,
it is not published, and translated works never leave this machine.

## Language policy

Everything that lives on GitHub must be written in English: code, identifiers,
comments, docstrings, commit messages, PR and issue text, and documentation.
Replies in chat follow the language the user writes in (usually pt-BR).

## Non-negotiable rules

- **One book at a time.** Never run two translations concurrently, and one chunk
  at a time. The queue API accepts `mode=next` only; the agent always runs with
  `--max-books 1 --stop-on-review --parallel 1`. `/api/translate` returns 409
  while the queue runner is active.
- **Never publish.** No translated work goes to a public repository, release,
  registry or shared drive.
- **Never rewrite the literary text** to fix metadata, tags or formatting.
  Metadata work is metadata work.
- **Secrets come from `.env`** and nowhere else. Never hardcode, log or commit a
  key, token or URL containing one. Before a commit, stop if the diff contains
  something that looks like a credential.
- **Do not start spending on cloud providers** without an explicit cap agreed in
  the conversation. Local Ollama is the default; cloud is opt-in per run.

## Layout

| Path | Purpose |
| --- | --- |
| `translate.py`, `translation_api.py`, `launcher.py` | Real entrypoints at the root |
| `src/literary/` | Literary queue, run control, checkpoints |
| `src/web/` | Flask UI, static JS and `static/locales/<lang>/<namespace>.json` |
| `scripts/` | Tooling: `queue_runner_agent.py`, `split_omnibus.py`, `benchmark_fase_d.py`, corpus builders |
| `tests/` | pytest suite. `tests/standalone/` holds manual scripts |
| `docs/` | Operational docs, rubrics, benchmarks |

No ad-hoc `check_*.py`, `test_*.py`, `debug_*.py`, `scratch_*.py` or `tmp_*.py`
at the root — they are gitignored on purpose. If a script becomes useful, move
it to `tests/standalone/` or `scripts/`.

## Docs

- `docs/ACTIVE_CONTEXT.md` — live state: branch, runtime, queue, next decision.
- `docs/project/README.md` — entry point and reading order for the project
  dossier: audit, environment, architecture, cost model, benchmark, roadmap and
  decision records.
- `docs/project/reviews/` — dated reviews with the evidence behind each model
  and quality decision.
- `docs/BACKLOG.md` — upstream triage, a snapshot from 2026-08-01; re-check
  against the code before using an item.

## Running

- Main app on `http://localhost:5000`; preview on `5001`.
- The queue needs the host agent running (`start-queue-agent.bat`,
  `scripts/queue_runner_agent.py`). Without it, the UI writes a pending request
  and nothing runs.
- Tests: `pytest` from the repository root.

## i18n rules

Every user-facing string must be translatable and must update immediately when
the UI language changes. Locales live in `src/web/static/locales/<lang>/` and
must stay in sync between `pt-BR` and `en`; `pt-BR` is the default.

- Static HTML: `data-i18n`, `data-i18n-html`, `data-i18n-attr` or
  `data-i18n-params`. Never raw human text.
- Rendered JS: wrap in `t('ns:key', { params })` and make the surrounding render
  re-run on `localeChanged`, or inject DOM carrying `data-i18n*` attributes.
- Forbidden: a literal written to `textContent`/`innerHTML`/`title`/`placeholder`/
  `aria-label`, a `t()` result cached at module load, a key missing from either
  locale, or a translation that drops a `{{placeholder}}`.

## Verification

- `pytest` for the Python suite; the i18n suite must stay green when locale keys
  change.
- Any change to EPUB generation or repair ends with EPUBCheck and a look at the
  resulting file in the reader.
- Report the commands you ran and their real result. Do not claim a check you
  did not execute.
