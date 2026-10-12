# ADR 0752: Bound bank-control candidate evaluation

- Status: Accepted
- Date: 2026-08-28
- Decision owners: ReconForge execution stream

## Context

The bank-statement control groups ledger records by normalized reference. Its
file readers already impose record and byte limits, but the domain function is
also a public typed boundary and could be called directly with a dense
duplicate reference. The previous unmatched-ledger projection additionally
searched every prior decision for every ledger record, creating avoidable
quadratic work.

## Decision

The domain control refuses inputs above 250,000 records per side, refuses more
than 10,000 ledger candidates for one normalized reference, and refuses more
than 1,000,000 candidate evaluations per run. These are fail-closed errors;
the control never truncates candidates or emits a partial artifact. The
existing duplicate-reference ambiguity behavior remains unchanged below the
limits.

The final ledger-coverage check materializes the referenced ledger IDs once
and uses set membership, preserving output semantics while removing the
quadratic `any(...)` scan.

## Consequences

- Dense reference collisions produce an explicit safe failure with a split or
  refinement instruction.
- Candidate evaluation and final coverage work have declared upper bounds.
- Existing normal and duplicate-reference fixtures retain their deterministic
  decisions and digests.
- This is algorithm/input safety evidence, not bank-source authenticity,
  provider integration, payment execution, posting, or production capacity.

## Verification

- `tests/test_bank_statement_control.py::test_bank_control_refuses_unbounded_duplicate_reference_candidates`
- Existing bank-control replay, API, persistence, and schema tests
- Full regression and release gates recorded in `docs/execution/EVIDENCE.md`
