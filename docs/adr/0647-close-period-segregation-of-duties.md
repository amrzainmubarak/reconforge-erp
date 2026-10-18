# ADR 0647: Enforce independent close-period reopen actors

## Status

Accepted — 2026-08-26

## Context

The generic close-management workflow recorded lock and reopen timestamps but
did not persist the actor who performed either transition. It therefore could
not enforce the segregation-of-duties rule that the actor who locks a period
must not reopen the same period. The consolidation-close workflow already had
that bounded control; the generic local and PostgreSQL close paths did not.

## Decision

Persist `locked_by` and `reopened_by` on local SQLite and PostgreSQL
`close_periods`. Existing locked/reopened records are backfilled with the
explicit sentinel `legacy-unknown`, so migration does not invent an actor and
future reopen operations remain fail-closed unless the actor is independent.
Both application adapters and database triggers require actor evidence for a
lock and reject a reopen by the locker. Reopening also requires the existing
locked state and a non-empty reason.

The change is additive and applies only to ReconForge close-workflow metadata;
it does not lock source-ERP postings or claim statutory/legal-book close.

## Verification and rollback

SQLite migration 44, PostgreSQL Alembic revision `0091_pg_close_period_sod`,
adapter contracts, and local SoD tests provide the code-level evidence. The
PostgreSQL downgrade refuses to discard lock evidence while locked or reopened
rows exist; the SQLite migration has no automatic downgrade and the safe
rollback is a restore of the pre-migration database backup. Remove this ADR
and revert the slice only with an equivalent independent-actor control
restored.
