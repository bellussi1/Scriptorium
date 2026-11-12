# Fork coupling inventory (prompt 1.1, 2026-11-12)

Read-only inventory of how this repository still refers to the upstream
`hydropix/TranslateBooksWithLLMs`. Method: `grep -rIn -i "hydropix\|TranslateBook"`
over the repository, excluding `venv`, `node_modules`, `.git`, `data`,
`translated_files`, `__pycache__` and `benchmark`. That matches 61 files. No
file was edited, no translation was run and no network call was made.

## Items that matter

| # | Path:line | Type | Changeable without breaking? | Notes |
| --- | --- | --- | --- | --- |
| 1 | `docker-compose.yml:13`, `docker-compose.remote-ollama.example.yml:15` | technical dependency | Yes, with a rebuild | The production-style compose pulls `ghcr.io/hydropix/translatebookswithllms:latest`, an upstream image. The dev compose builds locally (`docker-compose.dev.yml`), which is what the literary queue uses. |
| 2 | `src/utils/version_checker.py:24-38` | update check / telemetry | Yes (already done) | Off by default (`UPDATE_CHECK_ENABLED=false`). When enabled it reads `bellussi1/Scriptorium`, not upstream. |
| 3 | `src/core/llm/base.py:114` | User-Agent | Yes (already done) | Uses `GENERATOR_NAME` ("Scriptorium"). |
| 4 | `src/core/llm/providers/openrouter.py:445` | HTTP referer / title | Yes (already done) | No upstream Referer or X-Title; a comment records the removal. |
| 5 | `src/literary/kindle.py:146` | EPUB/Kindle metadata | Yes (already done) | `translator=GENERATOR_NAME`. |
| 6 | `src/config.py:468-470` | identity | Yes | `GENERATOR_NAME="Scriptorium"`, `GENERATOR_SOURCE` points to our repository. |
| 7 | `src/web/templates/translation_interface.html:912, 1760-1768` | URL (links) | Yes, but it is a product decision | Footer and help links point to upstream issues, discussions and the notifications doc. They are not network calls from the app, but a user is sent to upstream. |
| 8 | `src/web/static/locales/en/settings.json:98` | text | Yes | Describes notifications; no upstream URL found in the value itself. Checked only the line that matched. |
| 9 | `README.md:5, 243-248` | authorship credit and URL | Keep (legal) | Fork attribution, upstream link and "remains AGPL-3.0". |
| 10 | `docs/DOCKER.md:4, 163-164` | authorship credit and URL | Keep (legal) | Same attribution, and a note that the upstream image is not used for the literary queue. |
| 11 | `build/windows/*`, `build/macos/*`, `.github/workflows/build-*.yml` | identity (artifact names, wiki/issue URLs in release text) | Yes, but it is a rebrand task | The artifacts and the release notes still say `TranslateBook` and link to upstream wiki and issues. |
| 12 | `launcher.py:19` | identity | Yes | Data folder name `TranslateBook_Data`. Changing it moves user data; needs a migration. |
| 13 | `docs/project/AUDIT.md`, `docs/project/ENVIRONMENT.md`, `docs/ACTIVE_CONTEXT.md`, `skills/*` | docs | Yes | Mostly historical references. |
| 14 | `scripts/archive_v1_wiki.py:38`, `scripts/migrate_to_split_layout.py:5-8` | scripts | Yes, if the scripts are retired | Clone of the upstream wiki and benchmark file names from the upstream submissions. |
| 15 | `tests/**` (characterization goldens, unit tests) | test data | Keep | Regression data, not behaviour. |
| 16 | `src/literary/epub.py:617-644` | EPUB metadata | Not upstream-coupled | Calibre series fields only. |

## Five-line summary

- **Identity:** `TranslateBook` names in builds, data folder, release text and UI links.
- **Legal obligation:** the fork attribution and "remains AGPL-3.0" lines in README and DOCKER.md, and the LICENSE file itself.
- **Real dependency:** the upstream Docker image in `docker-compose.yml` (not used by the literary queue).
- **Network calls:** already off or renamed (version check off by default, User-Agent and Referer changed).
- **Still to decide:** whether UI links keep pointing to upstream, and whether the rebrand renames the data folder (needs migration).
