# ADR-0110: Atomic request idempotency with bounded replay

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-006

## Decision

Define a backend-neutral two-step idempotency service: atomically reserve a
tenant/scope/key against the SHA-256 digest of bounded request bytes, then
complete only with the exact reservation capability before expiry. Equivalent
completed requests replay the original bounded response; pending duplicates
report in-progress; changed request bytes conflict; expired records may be
atomically rebound.

Store only the capability digest, never its bearer value. Store response bytes
as bounded strict base64 plus a verified SHA-256 digest so SQLite JSON backup
and restore retain replay protection. Implement identical SQLite and
PostgreSQL contracts, with PostgreSQL forced RLS and fresh-connection owned
transactions.

## Consequences

- Concurrent requests have one owner and no ambiguous second execution.
- Tenant and operation scope are part of the primary identity.
- Restore retains completed responses, preventing a backup recovery from
  silently discarding the replay barrier.
- Callers must supply canonical UTC second-precision times and opaque,
  unpredictable owner capabilities. Capability generation and HTTP middleware
  integration remain composition responsibilities.
- SHA-256 bindings are deterministic integrity controls, not signatures or
  proof of request authenticity.
