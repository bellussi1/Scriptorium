# AGPL-3.0 compliance before rebranding (prompt 1.2, 2026-11-12)

Technical checklist, not a legal opinion. Checked: `LICENSE`, file headers, the
README and DOCKER.md, EPUB metadata written by the code, and the Docker and build
files. No file was edited.

## What the licence requires keeping

| Requirement (AGPL-3.0) | State in this repository | Gap |
| --- | --- | --- |
| Full licence text distributed with the work (§4, §5c) | `LICENSE` is the full AGPL-3.0 text. | None found. |
| Keep copyright and licence notices intact (§4) | The upstream copyright notices in files were not inspected individually. Only one file in `src/` contains "Copyright". | Confirm the upstream notices, if any, are still in the code the fork inherited. |
| Prominent notice that the work was modified, with the date (§5a) | README line 5 and 243-248 says "fork" and "remains AGPL-3.0". No per-file or release notice of the changes. | Add a modification notice (for example in the README and in the release text) that says what changed and when. |
| Source offer when users interact over a network (§13) | The web UI exists. The footer links to the upstream repository (`translation_interface.html:1760-1768`), not to this fork. `GENERATOR_SOURCE` in `src/config.py:470` points to our repository. | Check whether the UI exposes a source link to this fork. If not, add one. |
| Corresponding source for distributed binaries (§6) | The PyInstaller workflows build binaries from this code. The release text links to upstream wiki and issues. | Publish the corresponding source (this repository) with each binary release. |
| Do not remove or alter the licence terms (§7, §10) | `LICENSE` unchanged. | None found. |

## What is free to change

- Product name, UI text, logos and images, documentation and README wording,
  Docker image names, build artifact names and release notes.
- Network defaults that are ours to set: version check (already off by default),
  User-Agent and HTTP-Referer (already changed).

## Gaps with path:line

1. `README.md:5, 243-248`: attribution exists; the modification notice is only a
   sentence, with no date and no list of changes.
2. `src/web/templates/translation_interface.html:912, 1760-1768`: links point to
   the upstream repository, not to this fork. Check §13.
3. `docker-compose.yml:13`: the compose file pulls the upstream image. If images
   are published under this name, the publisher must provide the source.
4. `build/windows/*`, `build/macos/*`, `.github/workflows/build-*.yml`: binaries
   built from this fork but named and documented as upstream.
5. `src/config.py:470`: `GENERATOR_SOURCE` points to this repository; keep it in
   sync with the public repository.

## Needs a human decision

- Whether the fork keeps the upstream name in the README (attribution) and in the
  UI footer, or only in the README.
- Whether binaries will be published, and where the corresponding source will be
  offered (repository URL and tag per release).
- Whether a formal notice of modifications is written, and in which language.
- Whether a legal review is needed before any commercial use of the rebrand.
