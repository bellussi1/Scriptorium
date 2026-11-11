# Adjudicator calibration — Howling Dark (2026-11-11)

Read-only analysis. No gate change, no cloud call, no book reprocessing.

## Sample

`data/audits/adjudicator-calibration/sample.jsonl` has five claims extracted
from the two Howling Dark audits. `user_label` is empty; fill it with
`real_error`, `false_positive` or `unsure`. `prior_review` is the existing
manual reading in `review.md`, not your label.

| id | ch. | claim | Haiku verdict | prior review |
| --- | --- | --- | --- | --- |
| `hd-ch07-uptown` | 7 | `uptown` -> "lá em cima" | confirmed | false positive |
| `hd-ch17-ragdolled` | 17 | `ragdolled puddle` -> "membros desfazidos" | cleared | correct clear (style) |
| `hd-ch27-red-handed` | 27 | `Red-Handed Evolution` -> "Evolução de Mão Vermelha" | cleared | correct clear (calque) |
| `hd-ch37-glad` | 37 | `glad` -> "grato" | confirmed | false positive |
| `hd-ch27-nor-did-any-know` | 27 | `nor did any know` -> partial omission | not reviewed | pending |

The fifth row comes from the 09:39 audit, before the calibrated prompt. The
final candidate set no longer contains it. If it is a real error, the
calibrated first pass has a false negative that the adjudicator never saw.

## Provisional numbers

| metric | value |
| --- | --- |
| candidates in the final run | 4 |
| confirmed by the adjudicator | 2 |
| cleared by the adjudicator | 2 |
| manual false positives among confirmed | **2/2 = 100%** (95% CI 16–100%) |
| correct clears among cleared (provisional) | 2/2 |
| accuracy on the four final claims | 2/4 = 50% (95% CI 7–93%) |
| precision on confirmed | **0/2 = 0%** (95% CI 0–84%) |
| gate result | 2 confirmed > 1 -> fail |

The intervals are Clopper-Pearson. With n=4 the rate is not estimable; the
point is that the only two confirmed candidates in the sample are false
positives, and both cleared candidates look correctly cleared.

## Options

| option | mechanism | Howling Dark | evidence | cost / risk |
| --- | --- | --- | --- | --- |
| 1. Manual approval, gate unchanged | human approves the book | completed by human | current review recommendation | no automation change |
| 2. Threshold `<= 2` | 2 confirmed passes | passes | none: the sample has 0 confirmed true positives; a book with 2 real errors would also pass | weakens the gate without data |
| 3. Stronger second adjudicator (Sonnet) over candidates | both models must confirm | passes if Sonnet clears both | unmeasured; needs a blind run | ~US$ 0.01–0.02/book |
| 4. Two adjudicators + tie-break | both confirm -> fail; both clear -> pass; disagree -> human review | human review | unmeasured; needs the same blind run | ~US$ 0.01–0.02/book + review only on disagreement |
| 5. Human review on any confirmed candidate | adjudicator triages, human decides | human review | directly addresses the measured 0/2 precision | 2 candidates/book, minutes |
| 6. Prompt fix (locative / gender) | add rules to the confirmation prompt | passes if both stop counting | targets the two known false positives; unmeasured | $0, but risks overfitting to this book |

## Recommendation

1. **Immediate:** change the semantics from "confirmed count fails the book" to
   "confirmed candidate requires human review" (option 5). The adjudicator
   keeps triaging; it stops being the final judge. This is a proposal only; the
   gate is unchanged.
2. **Next:** label the five rows, then run a blind Sonnet adjudicator on the
   same claims. Adopt option 4 only if it clears both known false positives,
   confirms every claim you label `real_error`, and reaches precision >= 0.90.
   Otherwise keep option 5.
3. **Do not** raise the threshold as the primary fix. It passes this book for
   the wrong reason and would also pass a book with two real errors.

## Decision criteria

- Minimum sample for a rate: 30 claims across books, not 5.
- A second adjudicator is accepted only with zero known false positives among
  its confirmations and no new false negative on the labeled set.
- Any cloud run needs an explicit cap; a Sonnet pass over 2–4 candidates is
  within the current Claude balance but is not authorized by this document.
