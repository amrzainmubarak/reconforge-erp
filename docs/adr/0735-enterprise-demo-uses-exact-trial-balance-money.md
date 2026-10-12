# ADR 0735: Generate enterprise-demo trial balances with exact money

- **Status**: Accepted
- **Date**: 2026-08-28
- **Decision owners**: ReconForge maintainers

## Context

The enterprise demo is synthetic and local-only, but its trial-balance rows
enter the same CSV import path used by the account-reconciliation foundation.
The generator previously used binary floating-point literals and `round` for
those balances. That created an avoidable violation of the repository's money
invariant and could make the demo depend on binary representation before the
strict importer saw the values.

## Decision

Store demo account balances, entity factors, and period factors as exact
`Decimal` values. Bind each calculated balance to the entity currency through
`Money.from_exact(..., strict_precision=True)` and pass the resulting Decimal
to the CSV writer. The output remains compatible with the existing CSV schema
and strict account-import path, while the in-memory source records now carry
an explicit currency-bound exact amount.

## Consequences

- Synthetic trial-balance calculations no longer use binary floating point or
  implicit two-decimal rounding.
- USD, GBP, and MXN demo rows are validated against the currency registry and
  its configured minor-unit policy before they are written.
- The change strengthens demo/input integrity; it does not claim statutory
  accounting correctness, live source authenticity, or production assurance.

## Verification and rollback

The enterprise-demo exact-money regression, the enterprise-demo suite, the
full Python regression, Ruff, Mypy, Bandit, pip-audit, package build, YAML
validation, and diff checks are required for the slice. Rollback means
reverting E-1075, ADR 0735, and the focused test together; do not restore
float-based monetary fixture generation.
