# ADR 0504: Keep management-pack financial aggregation strictly exact

- Status: accepted
- Date: 2026-08-10
- Decision owner: ReconForge execution owner

## Context

Management-pack aggregation is a financial result surface. Its internal helper
parsers previously relied on the parser default, which is intentionally
legacy-compatible even though the current reconciliation result carries an
explicit financial-input policy.

## Decision

Use `STRICT_FINANCIAL_INPUT_POLICY` for management-pack amount, risk, WIP, and
close-completion parsing. Binary floating-point values therefore fail closed
instead of entering report calculations; malformed values that are explicitly
optional remain visible as unquantified values through the existing optional
helper behavior. Legacy parsing remains available only through named legacy
callers and does not change the public report schema.

## Verification

`tests/test_reports.py`, `tests/test_generated_report_ingress.py`, and
`tests/test_reconciliation_input_policy.py` pass; a regression explicitly
rejects `0.1` at the management-pack financial helper boundary. Ruff and the
complete local suite pass on the current tree.

## Boundary

This closes one report-ingress path only. Other explicitly classified legacy
compatibility callers, statutory accounting policy, live providers, hosted
matrix evidence, and production readiness remain open.

## Reversibility

Revert the strict policy arguments, regression, ADR, and E-667 evidence. No
database migration or persisted-data rewrite is required.
