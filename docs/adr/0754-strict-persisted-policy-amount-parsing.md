# ADR 0754: Strict parsing for persisted policy amounts

- Status: Accepted
- Date: 2026-08-28
- Decision owners: ReconForge execution stream

## Context

The PostgreSQL reconciliation worker re-applies the immutable `policy_amount`
stored in a run rule before claim and lifecycle authorization checks. Its
decoder used `Decimal(str(raw))`, which accepted a binary floating-point value
from decoded JSON and made it look like an exact policy amount. That weakened
the financial boundary of an authorization decision even though new API
submission data is strict.

## Decision

Decode a persisted `policy_amount` with `parse_exact_amount()`. Binary
floating-point values, missing values, malformed values, and non-finite values
are refused before the amount reaches policy evaluation. Exact text, integer,
and Decimal values remain supported; negative values remain invalid. The
worker returns its existing safe validation error without echoing the value.

## Consequences

- A stored financial exposure cannot silently cross the worker authorization
  boundary through a JSON numeric float.
- The policy amount used for claim/lifecycle checks follows the same strict
  parser as API and matching financial inputs.
- This is persisted-rule input evidence; it does not establish external IAM,
  distributed revocation, hosted effectiveness, posting correctness, or
  production authorization assurance.
- Existing valid exact-text persisted rules retain their behavior.

## Verification

- `tests/test_postgres_reconciliation.py::test_postgres_reconciliation_worker_rejects_binary_float_policy_amount`
- Existing PostgreSQL reconciliation worker, scope, policy, resume, and
  persisted-rule tests
- Full regression and release gates recorded in `docs/execution/EVIDENCE.md`

