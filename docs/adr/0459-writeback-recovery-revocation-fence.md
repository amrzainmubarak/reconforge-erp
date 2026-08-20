# ADR 0459: Recheck write-back recovery permission before provider status I/O

## Status

Accepted — 2026-08-09.

## Context

Write-back recovery reads a provider's idempotency/status endpoint after a
durably staged `DISPATCHED` intent. The route already authorizes the request
before loading the intent, but a permission can be revoked during the database
load. Querying a provider after that revocation would violate the least-
privilege boundary even though the operation is a read rather than a mutation.

## Decision

Re-evaluate the exact tenant/workspace `connectors.writeback.reconcile`
permission immediately before invoking the configured recovery transport. A
denial occurs before any provider I/O, leaves the staged intent and version
unchanged, and is safe to retry with the same idempotency key. The check is
server-profile only; local mode and the existing no-POST recovery invariant are
unchanged.

## Consequences

The revocation window between loading a dispatched intent and provider status
I/O is fenced and tested with a mutable policy hook. This remains a
process-local authorization boundary: distributed invalidation, provider
semantics, credential-vault operation, and production recovery SLOs require
separate runtime evidence.
