# ADR 0398: PostgreSQL close binds replay-verified PPA evidence

- **Date:** 2026-08-06
- **Status:** Accepted

## Context

Acquisition purchase-price allocation (PPA) is a deterministic, non-posting
evidence artifact. A close run that consumes PPA evidence must identify the
exact artifact and prove that it belongs to the run's period, reporting
currency, and worksheet entity. A tenant-wide artifact lookup alone does not
provide that lineage.

## Decision

Add migration `0069_pg_close_ppa_links` with a forced-RLS,
append-only `reconforge.consolidation_close_ppa_links` relation. The relation
uses run/artifact/entity uniqueness, foreign keys, and an immutable link
digest. The PostgreSQL close repository replays the PPA artifact before
linking, rejects posted artifacts, requires a linker independent of the run
preparer, and makes retries idempotent by the immutable digest. The close
bundle carries sorted PPA result digests as an additive field; older bundles
without that field remain readable. The server API exposes the operation only
through the PostgreSQL profile with strict artifact IDs and
`finance_core.manage` authorization.

## Consequences

- PPA evidence is attributable to a specific close worksheet without creating
  an ERP write-back or statutory posting path.
- Tampering, cross-period/currency/entity links, duplicate entity links, and
  self-linking by the run preparer fail closed.
- The downgrade refuses to discard non-empty evidence links.
- The live PostgreSQL runtime remains capability-gated until a disposable
  non-privileged PostgreSQL service is supplied; local static/API/bundle tests
  do not substitute for that runtime evidence.

## Boundary

This decision does not establish purchase-accounting policy, valuation
methodology, statutory recognition, goodwill approval, journal posting,
provider write-back, HA/DR, or production readiness.
