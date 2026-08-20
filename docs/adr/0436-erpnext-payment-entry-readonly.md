# ADR 0436: Add a bounded ERPNext Payment Entry read source

- Status: accepted
- Date: 2026-08-07
- Scope: `P4-CON-001`, `connectors.boundary`

## Decision

Add a read-only ERPNext `Payment Entry` adapter using the existing governed
network executor. It binds the exact resource path, token authorization,
bounded offset pagination, provider-side company filtering, local company
defense-in-depth, finite non-negative Decimal text, and deterministic response
digests. Zero-value payments, duplicate identities, mixed-company pages,
invalid cursors, and endpoint widening fail closed.

## Evidence boundary

Synthetic transport tests prove schema, auth, pagination, company scope,
endpoint hardening, digest, and secret-isolation behavior. They do not prove an
ERPNext tenant, provider-version compatibility, account mapping, posting,
settlement, write-back, or production availability.

## Rollback

Remove the adapter, tests, documentation, manifest entries, inventory entry,
and execution records. The existing ERPNext GL Entry and draft write-back
boundaries remain unchanged.
