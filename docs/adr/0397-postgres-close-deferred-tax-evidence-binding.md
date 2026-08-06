# ADR 0397: Bind Deferred-Tax Evidence to PostgreSQL Close Runs

## Status

Accepted for the bounded PostgreSQL server profile.

## Context

The deferred-tax bridge persists a deterministic, non-posting acquisition
artifact. Without a close link, the close evidence bundle cannot identify which
deferred-tax result was reviewed for a worksheet and period.

## Decision

Add migration `0068_pg_close_deferred_tax_links` with forced RLS,
append-only triggers, run/artifact/entity uniqueness, and an immutable link
digest. A link is accepted only for a prepared run, an independent linker, the
same business period and reporting currency, and a subsidiary entity present
in the replay-verified worksheet. The artifact is decoded and replay-verified
inside the link transaction. Close bundles include sorted deferred-tax result
digests, while older payloads without the additive field remain readable.

Expose the operation through `POST
/api/v1/consolidation-close/{run_id}/deferred-tax-evidence` with strict artifact
IDs and `finance_core.manage` authorization in server mode only.

## Boundary

This is evidence provenance only. It does not make tax, statutory, valuation,
journal-posting, ERP write-back, HA/DR, or production-readiness claims. The
live PostgreSQL runtime remains capability-gated and is not claimed without
`RECONFORGE_TEST_POSTGRES_DSN`.

## Reversibility

Downgrade refuses to discard non-empty links before removing the trigger,
function, index, and table. Removing the additive bundle field requires
retaining the compatibility reader for already emitted bundles.
