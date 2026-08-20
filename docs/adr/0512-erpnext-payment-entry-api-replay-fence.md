# ADR 0512: Bind ERPNext Payment Entry drafts to the authenticated API fence

## Context

The ERPNext Payment Entry adapter already had an exact, non-posting payload
contract and a pinned-HTTPS provider boundary. The authenticated write-back
API had been exercised with Journal Entry drafts, but not with the distinct
Payment Entry amount/account shape.

## Decision

Use the existing authenticated write-back intent lifecycle for the Payment
Entry operation: actor-bound proposal, independent maker/checker approval,
server-profile registration, optimistic version fencing, idempotent provider
dispatch, acknowledgement binding, and replay without a second provider call.
The API test uses synthetic data and an injected transport; it asserts the
exact `Payment%20Entry` endpoint, authorization metadata, operation/idempotency headers,
payload bytes, `docstatus=0`, and secret-free responses.

## Consequences

- The second ERPNext financial operation is covered at the API replay fence,
  not only at the SDK/transport boundary.
- Local Community mode remains non-networking; server network dispatch still
  requires explicit registration and feature enablement.
- No live ERPNext tenant, provider idempotency/status semantics, posting,
  compensation, statutory accounting, or production deployment is claimed.

## Rollback

Revert the API contract test, this ADR, the manifest entry, and E-701/D-506
records together. No migration or provider state is changed.
