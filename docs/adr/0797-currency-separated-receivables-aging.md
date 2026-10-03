# ADR 0797: Preserve currency boundaries in receivables aging

Date: 2026-10-03

Status: Accepted

## Context

The existing aging report added integer minor units from different currencies
into unlabeled buckets and one total. An arithmetically valid sum of USD cents
and JPY yen is not a financial balance. Server filtering must also recompute
aggregates from only authorized organization/entity items.

## Decision

Retain `/api/v1/receivables/aging` and its existing fields for empty or
single-currency results, adding `currency_code` (null when empty). Reject mixed
open currencies with an actionable error directing the caller to the additive
`/api/v1/receivables/aging-by-currency` endpoint. Its explicit schema version 1
has sorted currency groups, each with contributing items and integer minor-unit
buckets. There is no report-wide monetary total or implicit FX conversion.

Use one pure aggregation function in both repositories and server post-filtering.
Read invoice values and receipt allocations in one SQL statement. Apply the
existing read permissions and closed recursive field projection to the new route;
update the route inventory only after verifying its single authorized addition.

`as_of_date` retains its current semantics: age currently open balances against
due dates. It does not reconstruct balances before receipts recorded later than
the selected date. Historical open-item reporting needs a separate event/time
contract rather than changing this endpoint silently.

## Verification and compatibility

SQLite and actual restricted-role PostgreSQL tests cover mixed currencies,
empty/single reports, paid items, scope filtering, API behavior and nested field
projection. Existing invoice, credit, receipt, approval and CLI regressions run
alongside these cases. A new endpoint changes the closed authorization inventory
from 265 to 266 routes; removing it reproduces the original inventory digest.

There is no database migration or monetary rewrite. Single-currency callers keep
their previous totals. Clients of an invalid mixed-currency aggregate must adopt
the currency-grouped endpoint. Reverting the slice restores that known reporting
defect; disable the affected report instead if a deployment needs temporary
operational containment.
