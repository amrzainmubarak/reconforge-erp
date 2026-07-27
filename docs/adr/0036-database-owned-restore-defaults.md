# ADR 0036: Database-Owned Restore Defaults

- Status: Accepted
- Date: 2026-07-24
- Scope: local SQLite JSON backup restoration

## Context

When a supported backup row omitted an additive column, the restore bridge read
the trusted local schema's `PRAGMA table_info` default and attempted to evaluate
it in Python. Integer and quoted string defaults were special-cased; other
numeric text was converted through binary `float`, and SQL expressions could be
inserted as literal text rather than evaluated by SQLite.

Current financial defaults in the inspected schema are integer zero/minor-unit
or quoted canonical text, so no current snapshot corruption was reproduced.
The generic fallback nevertheless created a future precision and migration risk
for fractional defaults and a semantic risk for time/expression defaults.

## Decision

1. Do not parse or evaluate SQL column defaults in the restore application.
2. For each restored row, include only columns actually supplied by the backup
   or by an explicit versioned compatibility shim. Omit missing defaulted or
   nullable columns from that row's parameterized `INSERT` so SQLite applies its
   trusted schema definition.
3. Continue to reject a missing `NOT NULL` column without a default, unknown
   backup columns, unsupported tables, and rows with no usable columns.
4. Continue deriving identifiers from fixed allowlists plus strict identifier
   validation. Backup content never supplies SQL or a default expression.
5. Exact decimal schema defaults must be integer minor units or quoted
   canonical Decimal text. An unquoted fractional SQLite numeric literal may be
   evaluated as REAL and is not an exact-decimal storage policy.

## Consequences

- SQLite, rather than a partial Python SQL parser, owns default semantics.
- Exact quoted text defaults retain their full lexical value, and expression or
  time defaults execute according to the installed trusted schema.
- Insert column sets can differ by restored row. Queries remain parameterized,
  and dynamic identifiers remain validated/quoted.
- Existing complete backup rows use the existing preferred insert statement.
  Supported older rows keep their explicit `_restore_row_defaults` compatibility
  shims and use database defaults for other additive columns.

## Security and compatibility

This change does not execute backup-provided SQL. Table definitions come only
from the freshly created local schema/migration version selected after checksum
and version validation. The backup supplies parameter values only. Existing
backup formats, CLI commands, checksums, overwrite protection, foreign-key
verification, and migration replay remain unchanged.

## Rollback

Restoring the Python default parser is unsafe because it can change precision
or expression semantics. A rollback can preserve historical restored databases,
but future restoration should continue to omit defaulted columns or adopt an
equivalently exact database-native mechanism.
