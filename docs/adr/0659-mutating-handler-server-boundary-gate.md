# ADR 0659: Per-handler server-boundary regression gate

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

The existing API authorization inventory validated route contracts and checked
that a mutating route module contained at least one server-boundary marker. That
module-level check could miss a future handler added beside a guarded handler.
The result would be a source-level omission that might only be discovered after
manual review or runtime probing.

## Decision

Extend the static inventory to inspect every POST, PUT, PATCH, and DELETE
handler. Each handler must either:

- contain a direct reviewed marker such as `enforce_server_scoped*`,
  `enforce_server_tenant*`, or `server_identity_enabled`; or
- call a helper listed for that module in the explicit allowlist.

The allowlist is limited to reviewed server adapters/scope helpers, central
administration service wrappers, and local connection helpers that fail closed
in Server Profile. Authentication, SCIM, and WebAuthn remain explicit protocol
exceptions.

## Consequences

The gate catches handler-level omissions while remaining deterministic and
offline. It does not prove that a helper passes the correct scope arguments,
that RLS/SoD is complete, or that workers, exports, UI, external IAM,
distributed invalidation, HA/DR, or production deployments are governed.
Those remain separate evidence gates.

## Rollback

Revert the E-965 test, ADR, and execution documentation. No runtime or data
changes are involved.
