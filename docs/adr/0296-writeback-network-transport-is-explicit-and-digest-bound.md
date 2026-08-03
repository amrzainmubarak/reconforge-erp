# ADR 0296: Write-back network transport is explicit and digest-bound

- Date: 2026-08-03
- Status: accepted

## Decision

Add `WritebackNetworkRegistration`, `PinnedHttpsPostTransport`, and
`WritebackNetworkExecutor` as a separate opt-in provider boundary. The
registration declares one exact HTTPS egress endpoint, a credential reference,
allowed operations, bounded request/response sizes, a rate limit, and a finite
retry policy. The existing v1 connector manifest remains read-only.

Dispatch requires an already approved/dispatched intent, an enabled feature
flag, a matching connector and operation, and a short-lived payload resolver.
The resolver's bytes must hash exactly to `intent.payload_digest`. The same
idempotency key and payload are sent on every bounded retry. A secret resolver
is called only at dispatch; the secret is used to construct an Authorization
header and is never persisted or returned.

The provider response is a closed JSON acknowledgement envelope whose digest is
recomputed over its canonical fields. Its idempotency key must equal the intent
key before an acknowledged intent and replayable dispatch receipt are returned.

## Rationale

Intent persistence alone cannot prove a safe provider boundary. Keeping
payload resolution, egress, credential handling, transport, response schema,
and retry semantics behind an explicit adapter advances the connector SDK while
preserving the default no-network and read-only manifest posture.

## Evidence and limits

Synthetic injected-transport tests cover success, repeated idempotent retries,
payload-digest mismatch, secret isolation, endpoint/size/content-type guards,
provider-key mismatch, response-digest tamper, and pinned HTTPS request shape.
No vendor endpoint, customer credential, live ERP/bank interoperability,
compensation delivery, posting, hosted secret vault, or production reliability
claim is made by this slice.

## Rollback

Remove the transport module, exports, tests, ADR, and execution entries. The
existing append-only intent repositories and proposal-only API remain intact;
no external provider state is changed by rollback.
