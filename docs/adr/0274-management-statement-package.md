# ADR 0274 — Replayable management statement package

- **Status:** Accepted
- **Date:** 2026-08-03
- **Scope:** SQLite and PostgreSQL consolidation-close read drill-down

## Decision

Derive a `ManagementStatementPackage` from the already verified consolidation
worksheet. Group the exact reporting-currency management trial-balance lines by
account type, calculate section totals with `Decimal`/`Money`, require the
package total to balance to zero, and bind the artifact to the worksheet result
digest and a canonical artifact digest. Expose it as additive run drill-down in
both close adapters.

## Rationale

The close lifecycle had a deterministic management trial-balance primitive but
no explicit statement-shaped artifact for reviewers or API consumers. A
sectioned package improves explainability and reuse without inventing statutory
classification, posting behavior, or a second accounting calculation path.

## Compatibility and limits

The projection is additive and requires no migration. It is management-only
evidence: it is not a statutory financial statement, legal filing, accounting
opinion, or source-system posting. Acquisition/goodwill/equity-method rules,
cash-flow semantics, live source rates, and external assurance remain outside
this slice.

