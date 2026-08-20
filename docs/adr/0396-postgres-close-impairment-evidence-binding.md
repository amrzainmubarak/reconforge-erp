# ADR 0396: Bind Impairment Evidence to PostgreSQL Close Runs

## Status

Accepted for the bounded PostgreSQL server profile.

## Context

The impairment bridge now stores a tenant-scoped, replay-verifiable,
non-posting artifact. A close run could previously expose that artifact only
through a separate endpoint, leaving the close evidence bundle unable to prove
which impairment evidence was reviewed for the run.

## Decision

Add migration `0067_pg_close_impairment_links` with a forced-RLS,
append-only link table. A link is allowed only for a prepared run, an
independent actor, the same reporting currency and business period, and an
entity present in the replay-verified worksheet. The referenced impairment
artifact is re-decoded and replay-verified in the same transaction. One
artifact and one entity may be linked at most once per run; retries are
idempotent by the immutable link digest.

Expose the link through `POST
/api/v1/consolidation-close/{run_id}/impairment-evidence` in the PostgreSQL
server profile. Extend the close bundle with sorted impairment result digests;
old bundles without the additive field remain readable.

## Boundary

This proves evidence lineage and maker-checker binding only. It does not
decide valuation methodology, cash-generating-unit scope, tax, statutory
recognition, journal posting, ERP write-back, HA/DR, or production readiness.
The live PostgreSQL test remains capability-gated and is not claimed as passed
when `RECONFORGE_TEST_POSTGRES_DSN` is absent.

## Reversibility

The downgrade refuses to discard non-empty links before removing the trigger,
function, index, and table. Removing the API and bundle field requires a
compatibility reader for already emitted bundles.
