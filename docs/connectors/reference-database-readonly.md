# Reference database read-only connector

`reference-database-readonly` exposes two named query profiles:
`statement_lines_v1` and `trial_balance_v1`. It accepts no SQL text, table
name, column expression, or arbitrary parameter. Registration binds one exact
HTTPS gateway, one tenant, a runtime credential reference, and bounded row and
cell limits.

Rows use a closed schema with exact finite Decimal text, currency, date,
reference, and tenant identity. Results are sorted by stable record ID, cursor
paginated, duplicate-checked, tenant-verified, and hashed. The transport is
injected; the repository makes no database connection and stores no secret.

A concrete PostgreSQL adapter now lives in
`docs/connectors/postgres-named-query-readonly.md`. It is a separate
`database_source` manifest and does not change this synthetic HTTPS contract.
The adapter proves parameter binding, a non-privileged PostgreSQL role,
statement timeout/read-only setup, cursor replay, and tenant isolation against
synthetic views. TLS/vault operations, cancellation and replica consistency,
provider failure injection, schema migration compatibility, and ERP/bank
interoperability still require separate runtime evidence.
