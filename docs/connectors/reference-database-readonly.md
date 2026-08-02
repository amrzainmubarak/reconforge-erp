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

A live adapter must separately prove parameter binding, database role least
privilege, statement timeout, cancellation, replica/read consistency, retry
semantics, schema migration compatibility, and provider failure injection.
