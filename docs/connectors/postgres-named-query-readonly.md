# PostgreSQL named-query read-only source

`reference-postgres-readonly` is an experimental, provider-neutral adapter
for deployments that expose two read-only views:

- `reconforge_connector_statement_lines`
- `reconforge_connector_trial_balance`

The adapter accepts only the named `statement_lines_v1` and
`trial_balance_v1` profiles. It rejects arbitrary SQL and requires a
credential-free `postgresql://host[:port]/database` endpoint. The DSN is
resolved from a secret reference at runtime and its host, port, and database
path must match the endpoint. Credentials never enter registration digests,
logs, or returned rows.

Each read uses a bounded `READ ONLY` transaction, a statement timeout, a
transaction-local tenant context, parameterized tenant/cursor/limit values,
canonical finite Decimal text, stable ordering, and replay digests. The
deployment remains responsible for creating the views, granting only `SELECT`
to the application role, enabling RLS where appropriate, and operating TLS
and secret storage.

The repository test proves this contract against a synthetic PostgreSQL 16
service and a non-superuser role. It is not ERP/bank vendor interoperability,
write-back, high-volume capacity, HA/DR, or production-readiness evidence.
