# ADR 0619: PostgreSQL matching adapters require explicit currency

- Date: 2026-08-24
- Status: accepted
- Scope: PostgreSQL grouped and sequential matching input adapters

## Context

The matching adapters previously defaulted a missing currency to `USD` while
building a strategy request. That could turn a missing or malformed financial
field into a valid-looking cross-currency request and hide a data-quality
exception. PostgreSQL reconciliation inputs already carry a canonical
`currency_code`; the adapter boundary must not invent one when legacy or test
payloads omit it.

## Decision

Remove the implicit `USD` fallback from both PostgreSQL matching adapters. A
non-null canonical `currency_code` remains authoritative; otherwise a
non-null legacy/attribute currency may be used for compatibility. If no
explicit non-empty currency is available, the adapter raises its typed
validation error before invoking a strategy.

## Consequences

- Missing currency cannot silently match as USD.
- Currency mismatch and malformed currency remain visible to the existing
  strategy/data-quality boundary.
- Existing database rows with their required non-null currency continue to
  work; callers that omitted currency must now supply it or handle the typed
  error.
- No exchange-rate, precision, schema, or public API behavior is widened by
  this decision.

## Reversibility

Reintroducing a default would require a versioned compatibility reader and
explicit evidence that the source system supplies USD semantics. Until then,
revert only with a new ADR because defaulting financial currency is unsafe.
