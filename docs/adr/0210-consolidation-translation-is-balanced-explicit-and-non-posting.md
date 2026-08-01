# ADR 0210: Consolidation translation is balanced, explicit, replay-verifiable, and non-posting

- Status: Accepted
- Date: 2026-08-01

## Context

ReconForge already produces validated entity trial balances and contains separate
close and intercompany-control foundations. A useful consolidation path must not
start by summing unlike currencies or by silently choosing accounting policies.
It must also avoid implying that currency translation alone implements ownership,
eliminations, non-controlling interests, statutory statements, or source-system
posting.

Binary floating point, inferred two-decimal currency behavior, hidden rounding,
row-order identity, or selecting one of several eligible rates would make the
result impossible to reproduce and unsafe to review.

## Decision

The first Phase 4 finance slice is `consolidation-translation-v1`, an
Experimental Finance Core artifact contract.

- A request contains at least two entity trial balances. Every entity uses one
  explicit functional currency, one source trial-balance SHA-256, and signed
  balances that net exactly to zero before translation.
- Every source line carries a stable identity, source and group account codes,
  a closed account type, period, exact `Decimal` amount, currency, and explicit
  `closing`, `average`, or `historical` rate type plus a rate bucket. The bucket
  permits separate historical layers inside the same entity/currency without an
  arbitrary “first rate” choice. ReconForge does not infer an accounting standard
  from account type.
- Every foreign-currency rate is selected by exactly one
  period/base/reporting/rate-type/bucket key. The rate carries an identity,
  exact positive `Decimal`, source, source SHA-256, and timezone-aware effective time.
  Missing, duplicate, period-mismatched, reporting-currency-mismatched, and
  unused rates fail closed. Same-currency lines use a declared identity rule and
  reject supplied identity rates.
- The installed versioned currency registry controls precision and rounding.
  The artifact retains canonical Money policy and registry lineage, the
  unrounded translated value, per-line rounding delta, total unrounded
  translation difference, and total rounding delta.
- Input rows and rates are canonically sorted before SHA-256 calculation. The
  request digest determines the run ID. The result has a second digest and can
  be rebuilt from its declared inputs; merely recalculating a hash after changing
  a financial output does not pass verification.
- Different translation rates can unbalance an otherwise balanced set of entity
  trial balances. The engine exposes the exact pre-adjustment balance and an
  operator-policy-named translation adjustment proposal. The proposal is always
  marked `posted=false`; the post-proposal mathematical balance is zero, but no
  ledger entry, approval, elimination, or source write-back occurs.
- Results can be retained through the existing immutable object-store boundary.
  Keys are tenant/workspace scoped, content-addressed by integrity metadata, and
  identical replay is idempotent. Different bytes under the same run identity
  fail as a conflict.

## Consequences

- The slice gives later consolidation workflows one deterministic, auditable
  translation primitive without adding a second Money implementation.
- Operators must supply and approve account mapping, rate-type policy, rate
  sources, and the translation-adjustment account. ReconForge does not state that
  the chosen policy complies with IFRS, US GAAP, or local law.
- The artifact is not a consolidated financial statement. Ownership percentage,
  hierarchy/effective dates, investment/equity elimination, intercompany profit,
  non-controlling interest, acquisition accounting, period locks, maker-checker
  posting, remeasurement, and disclosure remain separate planned slices.
- Object-storage isolation is technical artifact storage, not WORM, retention,
  legal-record, production-key-custody, or external-assurance evidence.

## Rollback

Remove the optional domain/application/object-adapter files, schema, module
descriptor additions, and documentation. No SQLite or PostgreSQL migration,
ledger mutation, source-system call, or backward-compatible API/CLI contract is
changed by this slice.
