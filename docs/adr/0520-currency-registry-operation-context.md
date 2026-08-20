# ADR-0520: Freeze currency policy per operation

## Status

Accepted — additive immutable operation context; independently persisted
registry versions and live provider/production claims remain open.

## Context

The process-wide `CurrencyRegistry` is intentionally replaceable through an
explicit approved snapshot. An operation that resolves a currency repeatedly
could otherwise observe two policies if another explicit update happened
mid-run. Persisted workspace bindings (ADR-0519) identify the expected
snapshot, but do not themselves provide a historical snapshot to execute
against.

## Decision

Add `CurrencyRegistryContext`, an immutable, digest-checked view captured from
the installed registry or validated from a local snapshot without installing
it. `Money`, `MinorMoney`, and `ExchangeRate` accept an optional context, and
canonical-money restoration rejects registry lineage that does not belong to
the supplied context. Currency-registry reconciliation captures one context
at operation start by default and accepts an explicit context for replay.

The context contains only validated `CurrencySpec` values and the complete
registry manifest. It never mutates or switches the process-wide registry;
existing APIs remain backward compatible when no context is supplied.

## Verification

`tests/test_money_currency.py` proves snapshot isolation across an explicit
registry mutation, context-bound minor-unit and FX resolution, snapshot
round-trip, and canonical-lineage refusal. Currency-governance tests prove
that reconciliation retains the frozen context while the global registry
changes. Ruff, Mypy, and the full local regression are required for E-710.

## Boundary and rollback

This is per-operation determinism only. It does not persist independent
registry snapshots, select a historical workspace binding automatically, add
live rates, perform FX accounting, or prove hosted/production behavior.
Revert the context/type changes, tests, ADR, manifest, and E-710 records
together; no database migration or customer-data action is required.
