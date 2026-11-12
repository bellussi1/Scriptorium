# Deterministic checks on every file (prompt 3.2, 2026-11-12)

Measured on Howling Dark's current refined EPUB against its calibre source. No cloud call.

## Coverage matrix (current code)

| Check (from prompt 3.2) | Offender key in `scan_book` | Files covered |
| --- | --- | --- |
| Forbidden renderings | `forbidden` | 96 of 96 |
| Glossary adherence | `glossary_missing` | 95 of 95 paired files |
| pt-PT | `pt_pt` | 96 of 96 |
| English leakage | `english_leakage` | 95 of 95 paired files |
| Repetition | `repetition` | 96 of 96 |
| Per-file length ratio | `length_ratio` | 95 of 95 paired files |
| Dropcap | `dropcap` | 96 of 96 |
| All-caps | `caps` | 96 of 96 |
| Truncation and missing targets | `truncated`, `missing_targets` | 95 of 95 paired files |

The scan returns per-file records and the top offenders for each key (`offenders`). The
gate aggregates them without averaging a local error away: a single forbidden hit in one
file fails the gate (the gate reads `totals.forbidden_hits`).

## Runtime

- `scan_book` over 96 files: **3.9 s** on this machine (CPU).
- Totals now: forbidden 1, pt-PT 42 (12 blocking), glossary coverage 0.8101.

## Before and after

- The last saved audit (`data/audits/howling-dark-20261112T002734Z/`, run at 00:27 today)
  reports forbidden 4 in 4 files, glossary coverage 0.7857, pt-PT 42.
- The numbers changed because the refined file and the glossary changed after that run
  (the terminology pass and the reader pass). No code change in this step altered the check.
  The 3.2 change was already in place: all detectors cover every file.

## Not measured

- A matrix from before the per-file pass existed. No saved baseline was found.
