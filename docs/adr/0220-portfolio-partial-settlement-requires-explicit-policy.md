# ADR 0220: Portfolio partial settlement requires an explicit policy

- Status: accepted
- Date: 2026-08-02

## Decision

Extend the bounded portfolio matcher with `portfolio_allow_partial_settlement`, disabled by default. When enabled through the strategy request, exact groups remain eligible and unequal positive groups may be selected with settled amount and left/right residuals preserved in each decision. The portfolio objective remains bounded maximum coverage, then minimum aggregate difference, then maximum settled amount; non-overlap, partition, date, cardinality, and search limits remain mandatory.

## Consequences

Existing portfolio callers retain exact-only behavior. Partial settlement cannot be enabled accidentally by selecting portfolio mode. An unresolved equal-cost portfolio remains ambiguous, and no journal posting, write-back, or residual mutation occurs.

## Rollback

Remove the policy flag, portfolio candidate changes, tests, ADR, and execution records. No database or external state is changed.
