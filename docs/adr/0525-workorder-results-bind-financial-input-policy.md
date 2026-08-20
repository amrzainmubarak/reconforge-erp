# ADR 0525: Work-order results bind one financial-input policy

- Status: accepted
- Date: 2026-08-11
- Scope: Work-order reconciliation and combined management-pack reports

## Context

Work-order reconciliation already parsed monetary inputs with the current
strict default, but the result object did not retain the selected policy. A
caller could therefore combine a legacy Stock/GL result with a strict
work-order result and produce one management pack without a visible policy
conflict.

## Decision

`reconcile_workorders` accepts a validated, keyword-only
`financial_input_policy`, defaults to `strict-financial-input-v2`, passes it to
every monetary ingress, and records it on `WorkorderReconciliationResult`.
Current CLI and Studio callers bind strict-v2 explicitly. Management-pack
generation validates that Stock/GL and Work-order results carry the same
supported policy before creating any output; mixed or unsupported policies
fail closed. The Work-order CLI JSON and workbook metadata also expose the
selected policy rather than leaving the artifact unbound.

## Verification

Focused work-order, report, CLI-artifact, and reconciliation-policy tests prove
the result binding, artifact metadata, and mixed-policy refusal. Ruff and Mypy pass. Full regression,
security, package, and post-commit secret gates remain required for the slice
record.

## Compatibility and rollback

The new argument is keyword-only and defaults to the prior strict behavior;
existing direct callers remain valid. The result field has a strict default so
manual result construction remains compatible. Revert the policy plumbing,
report guard, tests, ADR, manifest entry, and E-715 records together if an
approved legacy aggregation path is required.

## Boundary

This is a local exactness and artifact-integrity boundary. It does not prove
statutory accounting, live source systems, posting, write-back, hosted CI,
HA/DR, or production readiness.
