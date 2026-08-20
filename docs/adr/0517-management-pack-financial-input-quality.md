# ADR-0517: Surface malformed optional report amounts as data-quality issues

## Status

Accepted — additive local/report evidence; no statutory or production claim.

## Context

Management Pack aggregation already used the strict financial-input policy and
kept unusable optional amounts out of totals. A malformed or missing optional
risk/amount field could nevertheless appear only as an unquantified count,
without a machine-readable data-quality exception explaining why it was not
used.

## Decision

Keep the strict parser and existing fallback aggregation semantics, but emit a
`financial_input_policy` error in the Data Quality Warnings sheet and the
optional `data_quality_warnings` JSON property whenever a present candidate
group has no valid value. Valid fallback fields suppress duplicate noise. The
issue records only frame/row/column/status metadata and never echoes the raw
financial value. Existing management-pack schema versions remain readable;
current writers add the optional property.

## Verification

Focused report and generated-ingress tests prove strict parsing, explicit
missing/invalid issue rows, valid-fallback behavior, no raw-value leakage, and
schema validation. Ruff and Mypy pass for the changed module.

## Boundary and rollback

This improves local evidence visibility only. It does not change ledger posting,
currency conversion, statutory policy, or external-provider behavior. Revert
the changed report/schema/test/ADR files together to restore the prior output
surface.
