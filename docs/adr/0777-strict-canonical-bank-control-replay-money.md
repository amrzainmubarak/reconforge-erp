# ADR 0777: Enforce strict canonical Money in bank-control replay

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Banking Controls

## Context

The bank-statement control already emitted canonical Money and verified its
nested decision digest. Its serialized replay verifier did not, however,
restore the tolerance and decision variances through the strict reader. A
re-signed artifact could therefore carry a representation such as `0.010`
that normalized to the same value instead of reproducing the producer's exact
Money serialization.

## Decision

Before the generic decision-artifact digest is accepted, require
`Money.from_strict_canonical_dict()` for `amount_tolerance` and every
non-null `amount_variance`. Malformed, policy-inconsistent, or
representation-drifted Money fails closed. Source ingestion remains unchanged:
the control still consumes local parsed CAMT.053 and ledger exports, performs
no posting or provider I/O, and retains its existing compatibility boundaries.

## Consequences and rollback

Bank-control persistence, API reads, and report verification now share one
exact serialized Money boundary. This strengthens deterministic replay without
changing the report schema, migration layout, or external integrations. The
change is reversible by reverting the code, regression test, ADR, and execution
records; no external state is mutated.
