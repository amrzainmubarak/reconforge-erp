# ADR 0033: Exact Studio Filters and Currency-Scoped Management Reports

- Status: Accepted
- Date: 2026-07-24
- Scope: server-rendered Studio exception filters, stock/GL result lineage, and the legacy management pack

## Context

The server-rendered Studio declared `min_amount` as a FastAPI `float` query
parameter. FastAPI therefore rounded the user's decimal text before the value
reached the existing Decimal comparison. Two distinct thresholds could become
the same binary float and change which exceptions were displayed.

The management pack had a second correctness problem. It summed Decimal values
under the process-wide Decimal context, rounded all monetary KPIs to two places,
did not retain currency on matched stock/GL rows, and could label a sum of
different currencies as the configured output currency. Invalid amount fields
could also disappear from aggregate totals without an aggregate-level count.

ReconForge has no FX conversion policy in this report path. A mixed-currency
total would therefore be an invented financial number.

## Decision

1. Keep the HTTP `min_amount` query value as bounded text until strict Decimal
   validation. Require a finite, non-negative, plain decimal; reject scientific
   notation and overlong input with a controlled HTTP 400 response.
2. Compare exact Decimal values and retain invalid exception amounts as missing.
   The browser field uses decimal text input instead of a two-decimal step.
3. Preserve the resolved currency on every matched stock/GL result row.
4. Resolve the configured report currency once from the versioned offline
   registry before creating report artifacts. Reject any explicit source/result
   currency that differs from it. Do not perform implicit FX conversion.
5. Sum monetary values under a local precision derived from the complete input
   set, independent of the ambient Decimal context. Apply the captured currency
   minor units and `ROUND_HALF_UP` only at the report-display boundary.
6. Publish schema-v1 `management_pack.json` with currency, minor units,
   rounding policy, policy digest, registry version/digest, the single-currency
   aggregation policy, and the legacy missing-currency assumption.
7. Count unquantified exception and WIP amounts explicitly. They are excluded
   from value totals but are never silently represented as valid zero amounts.

## Consequences

- Exact query text such as `0.100000000000000005` is no longer collapsed at the
  HTTP boundary.
- KWD, JPY, and other registered currencies use their registry precision rather
  than an assumed two decimals.
- Management-pack generation fails before creating its output directory if
  explicit currencies do not match `output_currency`. Multi-currency reporting
  requires a future explicit, sourced, effective-dated FX policy.
- Rows without a currency remain compatible with the legacy file contract and
  are interpreted as the configured report currency. This assumption is now
  recorded in the policy metadata and remains a migration gap.
- Additional result/report columns are additive. Existing metric names and the
  server-rendered Studio route remain available.

## Security and privacy

The amount query is length-bounded and validation failures return a constant
message without echoing user input. No new network call, telemetry, credential,
or raw-row logging is introduced.

## Rollback

The additive result/report metadata can be ignored by legacy readers. Rolling
back the exact query boundary, currency validation, or context-independent
arithmetic is unsafe because it would restore demonstrated decision-changing or
invalid-aggregation behavior. A future report-contract change must be versioned
and retain a compatibility reader or migration note.
