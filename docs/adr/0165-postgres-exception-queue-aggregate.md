# ADR 0165: PostgreSQL exception queue with append-only transitions

## Status

Accepted — 2026-07-28

## Context

The unified Exception Queue Application port had only a SQLite adapter. It
supports source-idempotent upsert, multidimensional listing, assignment, status
updates, bulk operations, and read-back. Phase 1 requires equivalent PostgreSQL
behavior without losing tenant/workspace boundaries or silently overwriting the
history of operational decisions.

## Decision

Add migration 0032 with tenant/workspace queue records and append-only transition
history under forced RLS. Implement all six exact Application signatures.
Preserve the port's existing flexible status behavior because it has no reason,
approval, or transition-policy parameters; do not fabricate maker-checker or
accepted-risk approval claims outside the contract.

Source identity, creator, and creation timestamp are immutable. Every create,
upsert, assignment, status change, and per-record bulk effect appends history
that a database trigger verifies against the current state. Database audit and
outbox effects share the transaction. Bulk operations deduplicate identifiers,
lock every target in deterministic order before mutation, fail atomically if any
target is missing, cap unique targets at 1,000, and derive each outbox identity
from resulting row versions. Lists and histories cap at 10,000 rows. Text,
identifier, date, risk, and status inputs are bounded and validated.

## Consequences

PostgreSQL gains explainable queue state without changing the SQLite facade or
API/CLI contracts. Repeated identifiers in one bulk request count once, which is
the safe idempotent interpretation. The current port cannot express comments,
reasoned acceptance, escalation events, SLA calendars, or maker-checker approval;
those require an additive contract version. Current-live PostgreSQL behavior
remains unclaimed until the optional non-superuser lifecycle/RLS test runs.
