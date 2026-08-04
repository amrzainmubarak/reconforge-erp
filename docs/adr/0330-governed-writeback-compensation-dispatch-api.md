# ADR 0330: Compensation dispatch is an explicit server-profile operation

## Status

Accepted — 2026-08-04

## Context

ReconForge now records a human-requested compensation and has a provider-neutral
transport capable of sending a separate compensation idempotency key. The
remaining gap was the API boundary that connects those contracts without
accepting financial payloads from a browser or marking an intent compensated
before a provider acknowledgement.

## Decision

Add `POST /api/v1/connectors/writeback/intents/{intent_id}/compensate/dispatch`
as a server-profile-only route protected by the existing privileged
`connectors.writeback.dispatch` permission and server scope re-evaluation. The
route:

1. requires `compensation_requested` and an optimistic expected version;
2. resolves a short-lived compensation payload from an explicitly configured
   in-memory application resolver, never from the request body or persistence;
3. requires the caller-provided SHA-256 digest to match those resolved bytes;
4. delegates bounded retries, HTTPS egress, secret resolution, compensation
   idempotency, and provider acknowledgement validation to
   `WritebackNetworkExecutor.dispatch_compensation`; and
5. appends `compensated` only after an accepted acknowledgement. A lost
   persistence response is retryable with the same `:compensation` key, while
   an already-compensated intent returns an idempotent replay response.

Local SQLite mode remains explicitly disabled for provider I/O. Missing
payload resolver configuration, malformed payloads, digest mismatch, provider
failure, stale versions, and invalid lifecycle states fail closed without
changing the persisted intent.

## Consequences

The write-back compensation path is now complete through the API boundary for
synthetic/server-profile providers: request, transport, acknowledgement, and
append-only persistence are separately testable. This remains a provider-
neutral contract; it does not establish live ERP/bank reversal semantics,
accounting posting, provider sandbox compatibility, signed connector package
admission, HA/DR, or production deployment readiness.

## Rollback

Do not remove the route while compensation evidence exists. Disable the server
profile or registration to stop provider I/O; retain append-only intent history
and migrate forward if the route contract evolves.
