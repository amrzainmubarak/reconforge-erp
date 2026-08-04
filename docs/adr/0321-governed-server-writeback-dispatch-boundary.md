# ADR 0321: Opt-in governed server write-back dispatch

- Status: accepted
- Date: 2026-08-04

## Decision

Expose `POST /api/v1/connectors/writeback/intents/{intent_id}/dispatch` as a
server-profile-only hand-off for an approved write-back intent. The route:

- requires the dedicated human-governed `connectors.writeback.dispatch`
  permission and an authenticated tenant/workspace scope;
- persists `approved -> dispatched` before invoking the injected
  `WritebackNetworkExecutor`;
- selects only a `WritebackNetworkRegistration` explicitly admitted in
  application state, with the registration's feature and operation allowlist;
- keeps the original idempotency key and payload digest through retries; and
- persists a provider acknowledgement only after the executor verifies the
  canonical response digest and idempotency binding.

The local/community profile fails closed with no network attempt. A missing
server executor or connector registration fails closed. A transport failure
leaves the immutable intent in `dispatched` so an operator can retry with the
same idempotency key; provider payloads, credentials, and responses are not
persisted.

## Rationale

The repository already had a provider-neutral transport contract but the API
stopped at acknowledgement reconciliation and was absent from the startup
authorization inventory. This slice closes the hand-off boundary without
inventing a vendor connector, enabling network traffic by default, or
weakening maker-checker and tenant isolation.

## Evidence and boundary

The local API test proves the default-disabled response, approved dispatch,
digest-bound synthetic transport acknowledgement, replay without a second
provider call, permission migration, and route-inventory inclusion (231
routes). The provider remains an injected synthetic sandbox; no ERP/bank
vendor, customer secret, vault, accounting posting, compensation delivery,
distributed quota, HA/DR, or production write-back claim is made.

## Rollback

Remove the dispatch route, permission migration, tests, inventory inclusion,
ADR, and manifest entry. Existing proposed/approval/acknowledgement routes and
the append-only intent migrations remain independently usable.
