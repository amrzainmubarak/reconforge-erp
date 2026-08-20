# ADR 0351: Acquisition deferred-tax bridge is deterministic and non-posting

- Status: accepted for the Phase 4 bounded financial-control slice
- Date: 2026-08-05

## Decision

Add `acquisition-deferred-tax-bridge-v1` as a pure, source-bound calculation
artifact. Each item provides an asset/liability kind, fair value, tax basis,
an exact decimal tax rate, and source references. The algorithm signs the
temporary difference by item kind, applies the installed currency registry's
explicit `ROUND_HALF_UP` policy to the tax effect, classifies positive effects
as deferred-tax liabilities and negative effects as deferred-tax assets, and
reconciles item totals into DTA, DTL, and net amounts.

The request requires a policy/version, source digest, and distinct preparer and
approver. Results are canonically ordered, digest-bound, replay-verifiable, and
always `posted: false`. The CLI and JSON Schema expose the same closed contract.

## Rationale

This closes a real acquisition-accounting calculation gap without pretending
to implement tax law. A deterministic bridge makes review and downstream close
workflow integration possible while keeping recognition, valuation allowances,
tax return treatment, statutory/legal-book posting, and journal authorization
under an explicit human-governed boundary.

## Evidence

- `tests/test_consolidation_deferred_tax.py` passes five focused tests.
- Ruff, Mypy, and `git diff --check` pass for the changed files.
- Schema: `docs/schemas/acquisition_deferred_tax_v1.schema.json`.
- CLI: `reconforge consolidation acquisition-deferred-tax`.

## Boundary and rollback

This does not prove statutory or legal-book tax accounting, live tax rates,
recognition, tax filing, journal posting, provider integration, HA/DR, or
production close readiness. Rollback is limited to removing the domain module,
CLI command, schema, focused tests, manifest entry, and execution records; no
database migration or persisted data is involved.
