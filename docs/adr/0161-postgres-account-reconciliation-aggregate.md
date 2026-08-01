# ADR 0161: PostgreSQL account-reconciliation aggregate

## Status

Accepted — 2026-07-28

## Context

Account reconciliation combines imported trial-balance facts, control templates,
materiality, preparation, independent review, completion, and roll-forward. The
existing Application port accepts exact arbitrary-scale decimal text and the
compatibility currency `LOCAL`; assuming two decimal places or silently coercing
binary floats would break the established financial contract.

## Decision

Add migration 0028 with five tenant-qualified forced-RLS tables for templates,
source rows, reconciliation records, support items, and append-only transition
evidence. Store PostgreSQL `NUMERIC` alongside canonical decimal text and never
use floating-point financial columns. Preserve the bounded ingress reader and
source checksum, filename-only provenance, deterministic business identifiers,
and atomic audit/outbox effects.

Enforce the exact Draft → Prepared → In Review → Reviewed → Complete lifecycle
in both the adapter and database. Preparation records the preparer; review must
be performed by a different actor. Financial scope, balances, materiality,
currency, risk, ownership, and support items become immutable after preparation;
completed records and transition history are immutable. Roll-forward creates
new Draft records with zero balances and retained governance metadata.

## Consequences

The adapter remains provider-local and performs no ERP writeback or network
call. PostgreSQL current-live behavior is not claimed until the optional
non-superuser lifecycle/RLS test runs against a configured service.
