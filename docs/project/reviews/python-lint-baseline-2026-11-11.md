# Python lint baseline — ruff (2026-11-11)

Baseline from the first ruff run on this repository, taken before any fix. The
change that adds ruff touches no `.py` file: it adds the config, the dev
dependency and this record. The findings are for a later sweep, after the active
branches (translation, single writer, UI, audit matcher) are merged.

Measured on the committed tree at `bdcb400`, the base of the branch.

## Configuration

Config file: `ruff.toml`. The repo has no `pyproject.toml`, so ruff's own file is
used.

- `target-version = "py312"` (as requested; see the open point below).
- `extend-exclude`: `venv`, `data`, `translated_files`, `node_modules`, `.claude`,
  `.git`, `benchmark/data`.
- `[lint] select = ["E4", "E7", "E9", "F", "I"]`: ruff's default set (E4, E7, E9,
  F) plus isort (I). F already is the pyflakes set, so no separate selector was
  added.
- No formatter, no line-length rule (E501 is not selected), no per-file ignores.

Ruff 0.17.4, installed into the project venv from `ruff>=0.6` in
`requirements-dev.txt`.

## Command

```bash
venv\Scripts\python.exe -m ruff check .
```

Run from the repository root. The counts below come from the same command with
`--output-format json`. The exit code is 1 because the baseline has findings.

The worktree used to produce this record has no `venv`, so the run used the main
checkout's interpreter. Same command, different path.

## Totals

1035 findings in 362 files. Fixable by `ruff --fix`: 745 safe, 53 unsafe
(`--unsafe-fixes`). No fix for the other 237.

## Counts by rule

| Rule | Name | Count | Fix |
| --- | --- | ---: | --- |
| I001 | unsorted-imports | 390 | safe |
| F401 | unused-import | 251 | 250 safe, 1 none |
| E402 | module-import-not-at-top-of-file | 143 | none |
| F541 | f-string-missing-placeholders | 93 | safe |
| F821 | undefined-name | 68 | none |
| F841 | unused-variable | 44 | 8 safe, 36 unsafe |
| E741 | ambiguous-variable-name | 12 | none |
| E712 | true-false-comparison | 12 | unsafe |
| E702 | multiple-statements-on-one-line-semicolon | 11 | none |
| E731 | lambda-assignment | 5 | unsafe |
| E401 | multiple-imports-on-one-line | 3 | safe |
| E701 | multiple-statements-on-one-line-colon | 2 | none |
| F811 | redefined-while-unused | 1 | safe |
| | **Total** | **1035** | |

## Counts by top-level directory

| Directory | Count |
| --- | ---: |
| `src/` | 441 |
| `tests/` | 408 |
| `scripts/` | 58 |
| `benchmark/` | 45 |
| root files (`translate.py`, `translation_api.py`, `launcher.py`) | 45 |
| `tools/` | 26 |
| `promo/` | 12 |
| **Total** | **1035** |

Files with the most findings: `src/config.py` (60), `translation_api.py` (27),
`benchmark/cli.py` (21), `translate.py` (17), `src/core/epub/xhtml_translator.py`
(15).

### Rule by directory

| Rule | src | tests | scripts | benchmark | root | tools | promo |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| I001 | 173 | 170 | 15 | 11 | 10 | 8 | 3 |
| F401 | 126 | 79 | 17 | 16 | 1 | 12 | 0 |
| E402 | 18 | 84 | 4 | 7 | 30 | 0 | 0 |
| F541 | 41 | 31 | 3 | 9 | 4 | 5 | 0 |
| F821 | 66 | 2 | 0 | 0 | 0 | 0 | 0 |
| F841 | 17 | 20 | 5 | 1 | 0 | 1 | 0 |
| E741 | 0 | 4 | 5 | 1 | 0 | 0 | 2 |
| E712 | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| E702 | 0 | 1 | 8 | 0 | 0 | 0 | 2 |
| E731 | 0 | 3 | 1 | 0 | 0 | 0 | 1 |
| E401 | 0 | 1 | 0 | 0 | 0 | 0 | 2 |
| E701 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| F811 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |

## Ten most frequent rules, one example each

1. **I001** `benchmark/__init__.py:10`: Import block is un-sorted or un-formatted
2. **F401** `benchmark/cli.py:29`: `benchmark.models.EvaluationScores` imported but unused
3. **E402** `benchmark/cli.py:25`: Module level import not at top of file
4. **F541** `benchmark/aggregator.py:207`: f-string without any placeholders
5. **F821** `src/api/blueprints/sample_routes.py:311`: Undefined name `SampleStateManager`
6. **F841** `benchmark/literary/runner.py:226`: Local variable `source_by_id` is assigned to but never used
7. **E741** `benchmark/wiki/generator.py:587`: Ambiguous variable name: `l`
8. **E712** `tests/standalone/test_token_variation.py:155`: Avoid equality comparisons to `False`
9. **E702** `promo/source/render.py:27`: Multiple statements on one line (semicolon)
10. **E731** `promo/source/audio.py:224`: Do not assign a `lambda` expression, use a `def`

## Findings that need a look before the sweep

- **F821 in `src/config.py` (59 of 68).** `_apply_reloadable_env_settings()`
  writes settings into `globals()` at runtime (line 108), so ruff cannot see the
  names. These are dynamic definitions, not missing ones. Ruff is wrong here.
- **F821 elsewhere (9).** String annotations name types that the file does not
  import: `"SampleStateManager"` in `src/api/blueprints/sample_routes.py`,
  `'XHTMLTranslationState'` in `src/persistence/checkpoint_manager.py`, and
  `'TTSConfig'` in `src/utils/file_utils.py` (imported only inside another
  function). These do not fail at import time, but they break type checkers and
  any code that calls `typing.get_type_hints`. Not checked: whether any path
  resolves them at runtime.
- **F821 `Path` in `tests/literary/test_benchmark_adapters.py:144` and `:171`.**
  Possibly a real NameError when that test runs. Not verified here; the pytest
  subset in this change includes `tests/literary`.
- **F841 (44, 36 of them unsafe).** Removing an assignment can drop a side effect
  when the right-hand side is a call. Review each by hand.
- **F811 (1).** Check that the earlier definition was not meant to be the one used.

## Recommendation for the sweep

**Fix automatically with `ruff check . --select I001,F541,E401 --fix`** (486 safe
fixes, formatting-level):

- I001 (390), F541 (93), E401 (3). I001 uses ruff's isort defaults, while
  `.pre-commit-config.yaml` runs isort with `--profile black`. The two should agree
  for this code, but that was not checked. Pick one as the authority before the
  sweep.

**Fix with `--fix`, then review the diff** (`ruff check . --select F401 --fix`):

- F401 (250 safe). Keep imports that exist for side effects, marking them
  `# noqa: F401` with a reason. Keep re-exports in `__init__.py` files.

**Fix by hand** (no safe autofix, or the autofix can change behaviour):

- F821 outside `src/config.py` (9): add `TYPE_CHECKING` imports or fix the names;
  check the `Path` case in `tests/literary`.
- F841 (44), E712 (12), E731 (5): the unsafe fixes exist; review each one.
- F811 (1), E741 (12, ambiguous `l`/`I`/`O` names), E702 (11) and E701 (2)
  (statements split onto separate lines).
- E402 in `src/` (18), `benchmark/` (7), `scripts/` (4): the import is movable.

**Ignore, with a reason, as per-file ignores in `ruff.toml`** (decide during the
sweep; none added here):

- E402 in the root entrypoints (30): import order is load-bearing.
  `translation_api.py` registers the MIME types before it imports Flask (see its
  header comment). Ignore per file with that reason.
- E402 in `tests/` (84): test modules bootstrap `sys.path` before importing
  project code (grep finds the `sys.path` pattern in 52 files under `tests/` and
  the root combined; not every file was read). Ignore for `tests/**`, or move the
  bootstrap into a `conftest.py`.
- F821 in `src/config.py` (59): the names are created at runtime (see above).
  Ignore that file for F821, or rewrite it so the names are explicit. The rewrite
  is a code change, so it is not part of a lint-only sweep.

## Open points

- `target-version = "py312"` was requested, but `deployment/Dockerfile` and
  `deployment/Dockerfile.dev` use `python:3.11-slim`. Ruff with `py312` does not
  flag 3.12-only syntax. Consider `py311` to match the runtime.
- The pre-commit isort hook and ruff I001 may disagree (see the sweep notes).
- No pre-commit hook was added. `ruff format` was not run.

## Not verified

- Counts cover the committed tree in the worktree. Ignored paths (`data/`,
  `translated_files/`) are absent from the worktree, and the main checkout may hold
  untracked, non-ignored Python files that are not counted here.
- Results are for ruff 0.17.4. Other versions can change the counts.
- No finding was fixed or confirmed as a bug, except where the text says so.
