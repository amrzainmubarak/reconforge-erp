# ADR 0370: World Bank public REST reference connector

- **Date:** 2026-08-06
- **Status:** Accepted

## Context

ReconForge already had a bounded public-financial evidence experiment, but the
connector SDK did not expose a concrete public REST implementation that could
be replayed through the same no-auth, exact-egress, pinned-HTTPS runtime. A
provider reference is useful for interoperability testing only when its
endpoint, response schema, pagination surface, and operational limits remain
closed and reviewable.

## Decision

Add `world-bank-public-readonly` as a built-in, read-only reference connector.
It pins the World Bank Finances One dataset `DS01556` / resource `RS00963` to
three declared JSON page offsets (`0`, `1000`, and `2000`) and uses the public
no-auth path. Each page is bounded to 1,000 rows and a 1 MiB response through
the shared network executor. Rows use a closed Pydantic schema with finite
`Decimal` numeric fields, and the connector emits request and canonical,
permutation-stable response digests.

The connector is community-supported and synthetic-sandbox capable. It does
not add write-back, credentials, redirects, runtime query construction, or
claims about freshness, service-level availability, banking/ERP integration,
or production readiness.

## Verification

Focused unit, schema-drift, no-authorization, manifest-substitution, and
permutation-determinism tests pass. An opt-in live page test fetched the first
1,000-row page through the pinned HTTPS transport and validated the closed
schema and 2,890-row source count on 2026-08-06. The existing eleven-artifact
public-financial experiment remains separately governed; a later full rerun
may be blocked by external source availability.

## Rollback

Remove the connector module, exports, tests, manifest entry, and this ADR. No
database migration or persistent-data rollback is required.
