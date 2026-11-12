# Real gate coverage (prompt 3.1, 2026-11-12)

Read-only. Sources: `scripts/audit_book.py`, `scripts/intra_run_audit.py`,
`src/literary/per_file_audit.py`, the queue gate in `src/literary/queue_runner.py`, and the
last Howling Dark audit in `data/audits/howling-dark-20261112T002734Z/`. No cloud call and
no edit.

## Detector matrix

| Detector | Where | Coverage | Cost | Case that escaped (known) |
| --- | --- | --- | --- | --- |
| Forbidden forms (glossary, word boundary) | `per_file_audit.scan_book` | 100% of files (96 in Howling Dark; 95 have a source) | CPU, seconds | none recorded in the last round |
| pt-PT blocking patterns | `per_file_audit` (`PT_PT_PATTERNS`) | 100% of files | CPU, seconds | none recorded |
| Glossary coverage per file pair | `per_file_audit` | 100% of paired files | CPU, seconds | none recorded |
| Length ratio 0.8-1.2 | `per_file_audit` | 100% of paired files | CPU, seconds | none recorded |
| Untranslated all-caps glossary terms | `per_file_audit` | 100% | CPU, seconds | none recorded |
| Queue gate (validation and EPUBCheck) | `queue_runner.py` | whole EPUB | CPU and a docker run for EPUBCheck | not a content detector |
| Meaning samples | `audit_book._sample_pairs` | 7 aligned samples in Howling Dark | local | not measured against labels |
| Meaning verdict (cloud model) | `audit_book._cloud_audit` | 0 samples: `cloud audit disabled` | cloud (off) | not run |
| Intra-run sample audit | `intra_run_audit.audit` | `--samples` (default 5) per run | local | not measured |

## Last round on Howling Dark

- The file count is **96** XHTML documents in the refined EPUB and in `per_file.json`
  (95 with a source pair). The prompt said 94; the current file has 96.
- The deterministic per-file checks ran on **all** of them (`totals.files = 96`). The
  fraction inspected by the deterministic detectors is therefore 100%.
- The meaning check inspected **7 samples** out of 266,676 words. The cloud verdict is
  disabled, so the meaning gate covered 7 paragraphs and gave no verdict on them.
- The gate failed: forbidden 4 hits in 4 files; glossary coverage 0.7857 (below 0.9);
  coverage below 0.8 in 47 files; length ratio outside 0.8-1.2 in 1 file; 27 untranslated
  all-caps terms.

## The known escapes

- `TIVAMOS NOSSO CARON` in chapter 24: golden fixture `tests/literary/fixtures/golden/caron_ch24`.
  No detector in the matrix checks for an untranslated English phrase in all caps; the
  glossary coverage counts terms, not phrases.
- `CHANTRY` on the chapter 76 dropcap: golden fixture `chantry_ch76`. The forbidden-form
  detector reads the glossary; a dropcap split into a separate node may not match a
  whole-word pattern. Not verified; the fixture is the only evidence.

## Findings

1. Only the meaning check is sampled. Seven samples per book cannot show a meaning error
   rate; with the cloud off, the meaning gate has no verdict at all.
2. The deterministic detectors cover every file, but they measure form and coverage, not
   meaning. Both known escapes are of kinds these detectors are not designed to see.
3. Costs are not measured per detector. They are seconds on CPU; EPUBCheck is the slowest
   part (a docker run).

## Next steps

- Status: the two known escapes are covered. `caron_ch24` is a truncated Portuguese term
  (`CARON` for `CARONTE`), caught by the `truncated_term` rule; `chantry_ch76` is caught by
  `forbidden_rendering` (case-insensitive, so `CHANTRY` counts). Both pass in
  `tests/literary/test_golden_set.py`. The first draft of this review said no detector saw
  them; that was true before commit c2a7fbc.
- Proper-noun forbidden forms (for example `Cantaria`) no longer count lowercase ordinary
  words such as the verb `cantaria`; see `_forbidden_occurrences` in
  `src/literary/per_file_audit.py` and `tests/literary/test_forbidden_case.py`.
- Raise the meaning sample size only when labels exist (see prompt 3.4).
