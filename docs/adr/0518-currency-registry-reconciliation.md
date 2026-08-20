# ADR-0518: Reconcile master-data currencies with the installed policy registry

## Status

Accepted — additive, read-only evidence; persistent per-tenant registry
selection and production claims remain open.

## Context

Master-data adapters persist currency references while the canonical
`CurrencyRegistry` carries version, digest, precision, and rounding policy.
Without an explicit comparison, a changed minor-unit reference or an unknown
code could remain hidden until a financial operation failed later.

## Decision

Add a bounded, order-independent reconciliation contract that compares only
currency code, `minor_units`, and `active` state. It reports malformed,
duplicate, missing-registry, and precision-mismatch issues without echoing
names or financial values. The result includes the installed registry version
and digest plus a separate input digest, and is exposed through local
master-data snapshots, the authenticated local API, the PostgreSQL server
master-data route, and the local CLI.

The operation is read-only: it never installs, switches, or mutates the
process-wide registry. SQLite currently stores currencies database-wide, so
the workspace is an evidence scope rather than a claim of persistent
workspace-specific selection. PostgreSQL uses the tenant-scoped currency
table. Persistent registry snapshots/selection and backend-wide execution
context remain future work.

## Verification

`tests/test_currency_registry_governance.py`, the master-data service/API/CLI
contracts, the application-port signature contract, Ruff, and Mypy pass.

## Boundary and rollback

This is policy-drift evidence only. It does not perform FX conversion, add a
rate feed, alter ledger posting, or establish statutory/accounting assurance.
Revert the governance helper, adapter/API/CLI exposure, tests, ADR, manifest,
and E-708 records together to restore the prior surface.
