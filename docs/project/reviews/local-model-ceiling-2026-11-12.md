# Local model ceiling, refine return and production scenarios (prompts 7.1–7.3)

Subject: Index-Translate-9B (Q4_K_M, Ollama) on *Howling Dark* (80 chapters,
266,730 words), the one book with a full before/after pair for the refine pass.
Figures marked **measured** come from the files named in each section. Figures
marked **estimate** are not measured on this path and say how they were made.

## 7.1 Error taxonomy

### Automated counts (whole book, after refine, `Howling Dark (pt-BR).refined.pre-casefix.epub`)

Source: `scripts/audit_book.py --no-cloud` on that file (audit `howling-dark-20261112T002710Z`).

| Type | Count | Examples | Refine changed it? |
| --- | ---: | --- | --- |
| Register / pt-PT | 42 hits (15.75 per 100k), 12 blocking | `estamos a` ×4, `de facto` ×3, `contacto` ×2, `demónio` ×1, `prémios` ×1; second-person forms in dialogue | No (42 → 42) |
| Forbidden form left | 2 | `animalcule` (ch. 27), `Chantry` (ch. 76) | Partly (4 → 2) |
| Glossary miss (name or term) | 10 | `Hadrian Marlowe` ×4, `Imperium` ×3, `Quiet` ×2, `Legion` ×1 | Coverage 0.7857 → 0.8067 |
| All-caps name not in the translation | 7 tokens | `BASSANDER` ×2, `JINAN`, `HADRIAN`, `KHARN`, `SAGARA`, `SMYTHE` | Not applicable |
| English leakage | 0.0002 | — | 0.0005 → 0.0002 |
| Repetition | 0.0 | — | 0.0003 → 0.0 |
| Length ratio | 1.0054; no outlier file | — | 1.0052 → 1.0054 |
| Dropcap issues | 0 | — | — |

### Human reading of the seven cloud-sample passages

Source: `data/audits/review-20261111-howling-dark/samples.jsonl`. Seven passages are
too few for frequencies; this is a qualitative reading, and the counts below are
passages, not rates.

| Type | Passages | Example |
| --- | ---: | --- |
| Accurate, no error found | 3 | P0 (Marlowe), P3 (Valka at the door), P4 (scholiasts and Chantria) |
| Terminology | 2 | P2 leaves `animalcule` in English; P5 renders `legionnaires` as `legionários` where the glossary says `Legião` |
| Calque or naturalness | 3 | P1 `ansiosos por uma luta` (for *spoiling for a fight*); P5 `traje de preto profundo`; P6 `no medo da luz` |
| Syntax | 1 | P1 `apressando` where an adjective participle reads better |
| Meaning error (inversion, omission, addition) | 0 | — |
| Idiom (lost idiom) | 0 | — |

### Conclusion on the ceiling

- Sentence-level meaning is mostly sound in this sample: three of seven passages
  are clean, and none inverts or drops meaning.
- The defects that a machine can detect are terminology (forbidden forms and
  glossary choices) and pt-PT register. Both are visible to the deterministic
  layer and can be fixed by data and by post-pass rules, not by a larger refine.
- Calque and naturalness, the errors a refine pass is supposed to fix, are the
  least measured part. Without a judge on before and after text there is no
  number for them (see 7.2).

## 7.2 Refine return on investment (Howling Dark)

Time, **measured**: refine ran from 05:09 to 06:13 local on 2026-11-11, about
**2 h 05 min**. It covered 63 of 94 documents, attempted 252 flagged segments,
accepted 149 (59%) and rejected 103 (`data/queue-runs/howling-dark.refine.report.json`).

Deterministic gain, **measured**. Before is the reader-repaired file the refine read
(`Howling Dark (pt-BR) - fixed.epub`). After is the first post-refine backup
(`…refined.pre-casefix.epub`). Same audit, no cloud.

| Dimension | Before | After | Change |
| --- | ---: | ---: | --- |
| Forbidden forms | 4 | 2 | −2 |
| Glossary coverage | 0.7857 | 0.8067 | +0.021 |
| English leakage | 0.0005 | 0.0002 | better |
| Repetition | 0.0003 | 0.0 | better |
| pt-PT per 100k | 15.75 | 15.75 | none |
| pt-PT blocking | 12 | 12 | none |
| Caps hits | 33 | 33 | none |
| Length ratio | 1.0052 | 1.0054 | none |

Not measured: prose, fidelity, naturalness and meaning errors. The only
judge output for this book is the cloud sample on the refined file (prose 4.0,
fidelity 4.0, meaning 0 confirmed), and there is no judge run on the
pre-refine text. So the refine's gain on those four dimensions is **unknown**,
not zero.

Which books benefit: this is one book, so no conclusion is supported. The
refine's measured effect here is small in deterministic terms and it did not move
pt-PT at all.

## 7.3 Production scenarios

Per book. Times are from the run reports (`duration_s`, translation stages) and
the refine log. Costs use the cost ledger, not current list prices.

| | A. Local only | B. Local + full refine | C. Hybrid (local + Haiku on flagged passages) |
| --- | --- | --- | --- |
| Time | 3.3 h (Howling), 3.4 h (Kingdoms), 5.0 h (Demon), **measured** | A + 2.1 h, **measured** | A + judge time, **estimate** (not run) |
| Cash | 0 (electricity not measured) | 0 | ≈ US$0.43 per book, **estimate**: 252 flagged segments × US$0.0017, the ledger's Haiku audit-call cost |
| Quality (deterministic) | 4 forbidden, coverage 0.786, pt-PT 15.75/100k | 2 forbidden, coverage 0.807 | Depends on the judge; not measured |
| Quality (prose, meaning) | Mostly sound in the sample (3 of 7 clean) | Unmeasured | Unmeasured |
| Risk | Terminology and register errors remain unless data and post-pass fix them | Costs 2 h for a small deterministic gain | Judge reliability not checked; price assumption not verified |

Budget snapshot (`data/budgets.json`, 2026-11-10): Anthropic balance US$1.54.
That covers the scenario C estimate for about three books, which should be
checked against current pricing before relying on it.

### Recommendation

Scenario A, with the fixes that do not need a model: move the remaining
forbidden forms and register rules into glossary data and post-pass repairs (see
`per-book-hacks-2026-11-12.md`), and stop paying 2 h per book for refine until it is
measured. The current Ashes of Man run has refine enabled; that choice is yours to
change, and I have not changed it.

What would have to be true to switch to B or C:

1. A paired judge run on the same passages before and after refine shows a
   material gain in prose or meaning, not only in forbidden forms.
2. The judge's cost per flagged passage is verified against current pricing.
3. The judge's verdicts agree with a human reading on a labelled sample.
