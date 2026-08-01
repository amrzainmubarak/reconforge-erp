# ADR 0193: Notifications are redacted, allowlisted, and at-least-once

## Status

Accepted on 2026-07-29.

## Context

Migration 0047 can create durable jobs atomically, but a hosted Team deployment
also needs a bounded polling runtime and optional operational notifications.
Sending an arbitrary outbox payload to an operator-provided URL or mailbox
would create SSRF, credential-disclosure, cross-workspace, and financial-data
exfiltration paths. Treating external delivery as exactly-once would also be
false: the process can fail after a provider accepts a request but before the
database records `Published`.

## Decision

- Migration 0048 stores immutable versioned email/webhook routes and immutable
  schedule-to-route subscriptions under forced tenant/workspace/entity RLS.
  Route destinations are retained only in the route registry; outbox payloads
  and append-only delivery evidence contain a SHA-256 destination binding,
  bounded identifiers, versions, and timestamps—never raw financial rows,
  amounts, arbitrary message text, or secret values.
- Notification egress is disabled by default. An enabled deployment supplies
  exact HTTPS webhook URLs, exact SMTPS relays, and exact recipient domains.
  Webhook URLs forbid credentials, query strings, fragments, plaintext HTTP,
  and redirects. Webhooks require an injected secret reference and use
  HMAC-SHA-256 over the canonical schema-v1 body.
- HTTPS and SMTPS transports resolve destinations at send time, reject the
  complete answer set if any address is non-global, and pin the selected
  validated address to the TLS connection while retaining the configured DNS
  name for certificate verification. Response bytes and timeouts are bounded.
- A hosted PostgreSQL scheduler worker enumerates a bounded, validated tenant
  set, uses one UTC instant per cycle, and opens one fresh connection per
  tenant. Schedule/job/dispatch/notification-outbox creation remains one
  database transaction; the worker makes no network call.
- Existing outbox leases provide bounded exponential retry, dead-letter, and
  explicit replay. A publisher router delegates unrelated domain events to the
  deployment's existing sink instead of consuming them as notifications.
  Every notification outbox transition appends a count/identity-only delivery
  event in the same database transaction.
- Delivery semantics are explicitly at-least-once. `notification_id` is the
  stable provider idempotency key, but a receiver/provider must enforce its own
  idempotency contract to prevent duplicate external effects.

## Consequences

- A route update requires a higher immutable version and a new explicit
  schedule subscription. Disabling/superseding a route stops both new and
  pending deliveries for that route version; pending events retry and then
  dead-letter rather than shifting to a different destination.
- DNS rebinding through a second resolver lookup is removed from the supplied
  transports, but public endpoint compromise, certificate-authority failure,
  provider retention, and operator-managed secret-store compromise remain
  deployment risks.
- Current evidence uses injected synthetic transports and a local PostgreSQL
  service. It does not prove real SMTP/webhook provider interoperability,
  internet-facing operation, HA, production secret custody, or exactly-once
  delivery.

## Rollback

An empty 0048 installation can downgrade to 0047 and re-upgrade. If a route,
subscription, notification outbox row, or delivery event exists, downgrade is
rejected before schema mutation. Retain a verified backup and use an approved
forward data migration; do not delete delivery evidence or rewrite a pending
event to bypass the guard.
