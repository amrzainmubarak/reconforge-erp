# ADR 0136: Durable-job static SQL identifiers

- Status: Accepted
- Date: 2026-07-28

## Context

SQLite and PostgreSQL durable-job adapters must encode and decode the same 25
columns in an exact order. They construct column and assignment fragments from
an immutable module-level tuple. Bandit B608 cannot distinguish that closed
identifier set from user-controlled string interpolation and therefore reports
the statements even though all record values use driver placeholders.

## Decision

Keep `_JOB_COLUMNS` as the single column-order authority. Mark only the seven
reported expressions with `nosec B608`, accompanied by source comments. Do not
disable B608 globally or exclude either repository. Preserve parameter binding
for every value and retain complete repository/application regression tests.

## Consequences

Bandit remains effective for every unreviewed SQL expression and returns no
findings on the current tree. The annotations are security review points: the
tuple must never accept configuration, request, file, plug-in, or database
content. A future need for dynamic identifiers must use an allowlisted typed SQL
composition facility and a new threat-model decision.

This change does not alter schemas, query text, persisted values, or public
contracts and can be replaced by fully literal statements later.
