# ADR 0202: Network connectors are data-only read jobs

- Status: Accepted
- Date: 2026-07-30
- Task: P3-ENT-007

## Context

ReconForge needs a safe connector extension boundary without turning signed metadata into permission
to execute third-party Python. Network reads also need cursor, idempotency, retry, rate, secret,
egress, crash-recovery, and evidence contracts before any vendor connector claim is allowed.

## Decision

The first network runtime accepts only a strict `network-connector-registration-v1` data object over
a signed/validated `connector-manifest-v1`. It supports read-only HTTPS GET with secret-reference
authentication. The endpoint must exactly equal one manifest destination. HTTPS URLs cannot contain
userinfo, query, or fragment. DNS is resolved once, every answer must be globally routable, the
selected address is pinned to the socket, and TLS continues to validate the declared hostname.
Redirects are returned as permanent failure and are never followed.

The executor requires a bounded idempotency key, bounded opaque cursor, response ceiling, declared
rate, and bounded exponential retry. It retries only transport and selected transient HTTP failures;
policy, SSRF, authentication, size, cursor, redirect, and other permanent failures are not retried.
Secrets are resolved at execution time through a provider-neutral protocol; the default resolver
is disabled and no secret is stored in the manifest, registration, result, checkpoint, logs, or
errors.

Every page runs as one generation-fenced durable-job partition. The response and next cursor are
stored in an immutable tenant object, whose digest is atomically committed with job progress. A
resumed worker loads only the latest committed effect, verifies storage/content/response and
registration digests, and continues at the next page. An identical uncertain object-store write is
accepted after re-read; changed bytes fail before a job effect is committed.

## Consequences

- Built-in local adapters and Community no-network defaults remain unchanged.
- The runtime is vendor-neutral and has no bundled live provider registration or production secret.
- Rate enforcement is per executor process; shared distributed quotas remain deployment work.
- The signed package authenticates data only. External executable connector installation remains
  prohibited. Write-back requires a new manifest schema, feature flag, authorization, approval,
  audit, compensation/idempotency design, and separate tests.

## Rollback

Disable/remove network registrations and the network worker. Existing connector page objects and
durable-job evidence are immutable audit artifacts and may be retained or removed only through the
normal governed retention process. No database migration was introduced.
