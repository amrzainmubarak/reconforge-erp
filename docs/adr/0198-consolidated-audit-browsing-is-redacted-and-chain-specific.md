# ADR 0198: Consolidated audit browsing is redacted and chain-specific

## Status

Accepted on 2026-07-30.

## Context

The PostgreSQL profile contains two tenant-scoped append-only audit chains:
the legacy ledger-control chain and the newer domain chain. Their event
payloads can contain actor labels, object identifiers, request identifiers,
reasons, and arbitrary bounded metadata. Returning a raw union would disclose
more than an administrator needs to inspect integrity and would incorrectly
suggest one global hash chain.

## Decision

- Add a backend-neutral audit-browsing contract and one static parameterized
  PostgreSQL union projection beneath transaction-local tenant RLS.
- Expose `GET /api/v1/admin/audit/events` only in the PostgreSQL profile. It
  requires human `audit.read`, current privileged assurance, and an
  operator-owned cursor signing key. Cursors bind tenant, resource, ordering,
  timestamp, source, and event identity.
- Return only source, event identity, tenant-local sequence, UTC timestamp,
  action, object type, actor/object/metadata SHA-256 digests, and chain/state
  hashes. Never return raw actor labels or IDs, object IDs, request IDs,
  reasons, or metadata text from this new route.
- Expose `GET /api/v1/admin/audit/verify` under human `audit.verify` and
  current privileged assurance. Verify ledger-control and domain chains
  independently; return stable issue codes, not raw rows or free-form errors.
  The combined display has no global hash-chain claim.
- Treat `audit.read` and `audit.verify` as human-only privileged permissions.
  Migration 0053 rejects future service-account grants. It is `NOT VALID` to
  preserve upgrades with historic grants; central policy still denies a machine
  principal until the operator removes the historic grant.
- Keep historical `/api/v1/audit/*` behavior for the Local/SQLite profile. Its
  PostgreSQL compatibility surface remains documented separately and is not
  the new administration disclosure contract.

## Consequences

- Administrators can page deterministically through provenance without broad
  identity or business-object disclosure.
- Existing audit sources stay immutable and independently explainable while
  the strangler migration is incomplete.
- This does not provide a global audit chain, external timestamping, immutable
  object-store evidence, legal retention approval, an accessible browser UI,
  full legacy audit normalization, compliance, certification, or independent
  assurance.

## Rollback

Remove the administration routes before downgrading 0053. Downgrade restores
the prior service-account database ceiling but does not remove audit data or
the existing historic grant records. Operators must review any grants created
after the policy change before relying on the older permission model.
