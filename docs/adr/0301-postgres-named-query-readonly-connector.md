# ADR 0301: PostgreSQL named-query source is an explicit read-only adapter

- Status: accepted
- Date: 2026-08-04
- Scope: `P4-CON-001`

## Decision

Add `PostgresNamedQueryTransport` as a concrete adapter for the existing
database row contract. It executes only the versioned `statement_lines_v1` and
`trial_balance_v1` SQL profiles over two deployment-provided views:
`reconforge_connector_statement_lines` and
`reconforge_connector_trial_balance`.

The registration uses a `database_source` manifest, pins one credential-free
PostgreSQL endpoint, and resolves a DSN only at call time. The DSN host, port,
and database path must match that endpoint. Each transaction is explicitly
`READ ONLY`, uses a bounded statement timeout, sets a transaction-local tenant
context, binds every value as a parameter, and returns canonical finite Decimal
text. No arbitrary SQL, writes, provider payloads, or write-back are exposed.

## Rationale

The prior database connector was intentionally transport-injected and
synthetic. A concrete local PostgreSQL runtime gate advances the connector
workstream without mislabeling export profiles or a fake HTTPS gateway as a
live database integration. Fixed named queries keep the attack surface and
schema contract reviewable while still allowing a deployment to expose its
own read-only views.

## Evidence boundary

The live test uses synthetic rows, a non-superuser/non-`BYPASSRLS` role, a
single PostgreSQL node, and a local CI-style service. It proves named-query
execution, read-only transaction setup, endpoint/credential binding, cursor
replay, canonical Decimal conversion, and tenant isolation. It does not prove
ERP or bank provider interoperability, TLS/secret-vault operations, schema
compatibility with a vendor, write-back, throughput, HA/DR, or production
readiness.

## Rollback

Remove the adapter, registration, tests, documentation, and CI test entry.
The existing synthetic `reference-database-readonly` transport and all local
Community behavior remain intact; no external database state is modified by
the adapter itself.
