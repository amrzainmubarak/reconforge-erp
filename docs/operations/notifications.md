# Optional notification operations

## Maturity and claim boundary

Email and webhook notifications are an experimental single-node PostgreSQL
boundary. The repository has synthetic tests with injected transports; it has
not sent mail or webhooks to a real provider and is not evidence of hosted,
HA, production, compliance, or exactly-once operation.

## Secure activation

Network delivery is off by default. An operator must explicitly provide an
enabled `NotificationEgressPolicy` containing:

- every exact HTTPS webhook URL, with no query, fragment, or embedded
  credential;
- every exact `smtps://host:port` relay; and
- every allowed recipient domain.

Register routes only through `NotificationApplicationService`, then create an
explicit schedule-version subscription. Webhook routes reference a secret in
an injected secret manager; the secret value is never accepted by the route
model, database, event payload, audit evidence, or log context. Rotate a route
by registering a higher version and subscribing it explicitly.

## Runtime composition

Run `PostgresSchedulerWorker` with a trusted, bounded tenant supplier. It uses
one fresh connection per tenant and performs no network calls. Run the existing
`PostgresOutboxWorker` separately with an `OutboxPublisherRouter` that sends
only `notification.scheduler_dispatch.v1` events to
`NotificationOutboxPublisher` and delegates every other event to the existing
domain-event publisher.

Choose `HttpsWebhookTransport`, `SmtpsEmailTransport`, or both through
`NotificationTransportRouter`. Supply a reviewed secret resolver. The built-in
disabled resolver always fails. Do not implement a fallback that sends to an
unlisted endpoint or includes the route destination in exception text.

## Delivery and recovery

Delivery is at-least-once. The stable notification ID is sent as the webhook
`Idempotency-Key` and email `Message-ID`, but the receiver/provider must retain
and enforce that identity. A process failure after external acceptance and
before the outbox acknowledgement can cause a duplicate.

Inspect tenant-scoped states in `reconforge.outbox_events` and immutable
transitions in `reconforge.notification_delivery_events`. Retry is bounded by
the outbox worker configuration. A `Dead` event requires operator review of:

1. route version and destination digest;
2. current egress allowlist;
3. secret-reference availability;
4. certificate/DNS/provider status; and
5. whether the provider already accepted the notification ID.

Replay only after that review. Never mutate the payload, destination, route,
or append-only delivery evidence. A changed destination requires a new route
version and future subscription.

## Migration and rollback

Migration 0048 can downgrade to 0047 only while routes, subscriptions,
notification outbox rows, and delivery evidence are empty. A non-empty
downgrade fails before mutation. Back up and follow an approved forward data
migration; do not remove evidence to force a downgrade.
