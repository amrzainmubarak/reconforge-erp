# ADR 0174: PostgreSQL federation replay and identity links

## Status

Accepted — 2026-07-28

## Context

Process-local replay state cannot protect multi-worker deployments. External
issuer-subject pairs must resolve to existing local users without persisting raw
assertions or silently provisioning privilege. Federation login must issue the
same revocable hash-only session used by server identity.

## Decision

Migration 0034 adds forced-RLS replay, identity-link, and append-only event
tables. Persist SHA-256 identities for assertions and issuer-subject pairs, not
their raw values. Consume replay through one `INSERT ... ON CONFLICT DO NOTHING`.
Require an explicit administrative link to an active local user. Before session
issuance, lock link/user rows and require every mapped external role to already
exist on that local user. Reuse the existing hash-only session repository. All
operations share the caller-owned tenant transaction.

## Consequences

Replay, linking, role containment and session issuance are durable, tenant-bound
and transactionally composable. This is not JIT provisioning. Link disablement
prevents new federation sessions but does not itself revoke existing sessions;
logout/revocation orchestration and API integration remain before P3-ENT-001 can
close.
