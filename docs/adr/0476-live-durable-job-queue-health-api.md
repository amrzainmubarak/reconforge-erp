# ADR 0476: Exercise the durable-job queue-health API against live PostgreSQL

## Status

Accepted locally; GitHub publication is intentionally deferred by owner policy.

## Context

ADR 0475 added an authenticated queue-health route and proved its local SQLite
path plus an injected server boundary. The route still needed a real HTTP
exercise through PostgreSQL identity authentication, service-account policy,
tenant RLS, and the durable-job repository before its server behavior could be
described as runtime evidence.

## Decision

- Add an opt-in live test guarded by `RECONFORGE_TEST_POSTGRES_DSN` and a
  non-privileged `RECONFORGE_TEST_POSTGRES_APP_USER`.
- Provision two disposable tenants, a least-privilege `ops.read` service
  account, the durable-job schema, and the scope-authority schema. Submit one
  synthetic queued job only in tenant A.
- Call the route through `TestClient` with the real PostgreSQL identity pool.
  Assert the tenant/workspace/entity projection, queued count, queue depth,
  absence of job identifiers/digests, and rejection of the credential in
  tenant B.
- Keep the test capability-gated: a missing disposable service is a declared
  skip, not a claim of hosted or production evidence.
- Invoke the complete operations API test file explicitly in the
  `server-boundaries` workflow after the generated parity matrix, so this
  route cannot silently disappear behind a narrowed `-k` selection.

## Evidence and limits

The live PostgreSQL 16.14 non-privileged run passes the HTTP route contract
locally. This proves one disposable single-node service path with synthetic
data. It does not prove distributed policy invalidation, queue HA, host loss,
throughput, provider behavior, hosted CI, or production SLOs.

## Rollback

Remove the live test and this ADR. No product schema, API wire contract, or
stored data format changes are introduced.
