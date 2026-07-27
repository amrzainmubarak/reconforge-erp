# ADR 0046: Schema-Validated Risk Register Governance

- Status: Accepted
- Date: 2026-07-25
- Scope: Repository risk ownership, scoring, evidence, actions, and review schedule

## Context

The human-readable risk table contained 17 useful narratives but lacked
explicit owners, trigger conditions, likelihood, residual ratings, and review
dates. Its IDs were also displayed out of numeric order. The closing note made
all bounded-context maintainers implicit owners, which is not an actionable or
machine-verifiable governance contract. P0-011 requires unique IDs, owners,
triggers, likelihood/impact, mitigations, residual risk, and review dates to be
validated.

## Decision

1. Make `docs/risk-register.yaml` the normative governance source and retain
   `docs/risk-register.md` as the concise human narrative.
2. Keep all existing R-001 through R-017 risks. Use role-based owner labels,
   not named people or unverifiable staffing claims.
3. Score inherent risk as likelihood 1-4 multiplied by impact 1-4, with fixed
   thresholds: Low 1-3, Medium 4-7, High 8-11, Critical 12-16. Require residual
   rating not to exceed the inherent rating.
4. Require a concrete trigger, implemented mitigations, repository-contained
   evidence paths, residual rationale, next actions, cadence, and ISO review
   date for every risk.
5. Validate the closed schema, sequential/unique IDs, rating calculation,
   evidence-path containment/existence, review cadence, and Markdown/YAML ID
   parity in CI tests.
6. Include the normalized register, schema, and readable narrative in sdist as
   project governance evidence; do not add them to the runtime wheel.

## Consequences

- P0-011 is complete for the defined normalization exit evidence.
- A missing risk, stale/nonexistent evidence reference, inconsistent rating, or
  overdue-by-declaration review schedule now fails the focused gate.
- Role labels identify accountable areas but do not prove staffing, review
  completion, risk acceptance, or control effectiveness.
- This register remains project risk governance, not an enterprise GRC system,
  independent assessment, or compliance certification.

## Rollback

Do not return to prose-only implicit ownership. If YAML is replaced, the new
source must preserve schema validation, all risk IDs and history, deterministic
rating rules, evidence references, and review cadence before the old source is
removed.
