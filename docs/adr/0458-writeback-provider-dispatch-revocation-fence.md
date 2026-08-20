# ADR 0458: Recheck write-back permission before provider mutation

- **Status:** Accepted
- **Date:** 2026-08-09
- **Decision owners:** ReconForge maintainers

## Context

The write-back API durably stages an approved intent as `dispatched` before
calling the provider. A dispatch permission could be revoked after that
transaction but before the external POST or compensation mutation.

## Decision

Retain the request-time server-scope check and add a second
`connectors.writeback.dispatch` evaluation immediately before provider
mutation for both normal and compensation dispatch. A denial leaves the
staged intent retryable and performs no provider I/O. No permission check is
performed after a successful provider effect because a completed external
mutation cannot be atomically undone.

## Consequences

- Revocation in the staging-to-provider window fails closed without an
  external write.
- The staged intent remains available for an authorized retry or the existing
  idempotency-status recovery flow.
- This is request/process-local policy evidence; distributed cache
  invalidation, live vendor semantics, vault operation, and production
  write-back remain unproven.
