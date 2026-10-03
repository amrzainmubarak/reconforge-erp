# ADR 0792: Capture monetary interpretation with each Finance Core entry

Date: 2026-10-03. Status: implemented; broader release acceptance pending. Scope: PROD-015.

## Context

Reproductions show a stored 100.00 entry becoming 10.000 after a currency precision
edit, installed registry drift changing new minor units, and a functional-currency
edit relabeling a trial balance. A tenant-wide currency check cannot rely on
workspace-filtered entry queries: sibling references may be invisible under RLS.

## Decision

Capture one verified currency registry policy within the write transaction and
persist its code, precision, rounding policy, registry version and snapshot digest
with every new Finance Core entry and inventory valuation document. Reuse the existing governed registry snapshots.
Reads, draft replacement, reversal and trial balance use that retained policy.
Reject a missing/tampered binding instead of consulting mutable installed state.

Freeze economic currency fields (code/precision) after currency-row creation;
name and active metadata remain editable. This intentionally removes even unused
precision edits. Versioned policy changes require a later explicit operation.
Protect entity functional currency at the database boundary without widening
request scope or introducing an RLS-bypassing SECURITY DEFINER helper. Keep both
local SQLite and PostgreSQL behavior aligned through additive migrations.

Historical rows without retained policy remain explicitly unverified. Never
populate them with today's digest as supposed historical proof. Preserve their
identities and raw minor-unit data for compatibility and review; exact monetary
projection and financial mutations must return an actionable policy-unverified
failure until a separately governed attestation can establish interpretation.
Publish migration and compatibility notes, and guard rollback when policy-bound
rows exist. No amount rescaling or destructive historical rewrite is authorized.

## Acceptance and limits

Verify exact amounts, not only balanced totals, across registry changes, workspace
rebinds, sibling-workspace metadata access, independent tenants, direct SQL edits,
concurrent creation and migration/restore. Financial API/UI claims wait for these
tests. This slice does not establish policy capture for every AP/AR or
consolidation writer; that inventory remains explicit follow-up work.

Generated inventory GL entries reuse the valuation policy, reversals reuse the
original GL policy, and FIFO consumption verifies the contributing source policy
before changing layers. Differing registry provenance requires explicit
reconciliation even when its current scale happens to agree. Public inventory
response schemas retain their existing shapes.

SQLite migration 47 and PostgreSQL 0094 implement this boundary. Reviewed logical
restore preserves wholly unverified legacy rows in an unpublished temporary
database, reinstates insert guards and validates captured policies before
publishing. Populated PostgreSQL downgrade refuses to discard captured policy.
See [upgrade contract](../operations/finance-policy-upgrade.md) and
[focused verification](../execution/FINANCE_POLICY_2026-10-03.json).
