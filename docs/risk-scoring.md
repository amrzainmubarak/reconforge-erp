# Risk Scoring

ReconForge ERP scores exceptions from 0 to 100 using deterministic, explainable factors. Scores are intended to prioritize review, not prove fraud or error.

| Score | Level | Typical escalation |
| ---: | --- | --- |
| 0-30 | Low | Process owner |
| 31-60 | Medium | Department manager |
| 61-80 | High | Finance controller |
| 81-100 | Critical | CFO / Internal audit |

## Risk Factors

- Monetary impact.
- Missing GL entry.
- Missing stock movement.
- Duplicate reference.
- Missing work order.
- Old WIP.
- Direct purchase fitting.
- Missing old-part return.
- Cancelled PO linkage.
- Closed job without invoice.
- Repeated repairs.
- High variance.
- High-risk account or user.
- Backdated transaction.
- Manual journal.
- Weekend or after-hours posting if data exists.

## Data-quality behavior

- Invalid or malformed monetary factor values are treated as non-numeric in risk calculations and therefore do not add amount/variance risk points.
- Invalid `aging_days` values are treated as 0 for scoring purposes to keep batch scoring deterministic and failure-safe.

## Output

The risk engine returns score, level, explanation, recommended action, responsible department, escalation level, and suggested audit note.

## Auditor Guidance

Use the score to prioritize evidence review. A High or Critical result should be reviewed with source records, match candidates, triggered rules, management explanation, and closure evidence.
