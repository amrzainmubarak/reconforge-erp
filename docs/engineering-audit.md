# Engineering Audit (Baseline)

## Current-state assessment

This repository has a functioning reconciliation engine for stock-to-GL and workshop controls with practical safety improvements already present:

- Deterministic stock-to-GL matching using a min-cost assignment model.
- Explicit handling of invalid financial amounts with exception rows.
- Signed metadata artifacts and review/binder generation flow.

Notable gaps remain in exchange for the product claims in this goal:

- Deterministic matching and exception contracts are not consistently applied across all modules.
- Empty exception aggregation can still fail in work-order and evidence paths.
- Monetary handling remains float-backed in several core modules.

## Findings

### Critical

None identified from the inspected baseline.

### High

- **Finding:** Work-order reconciliation raises `ValueError` when all work-order exception frames are empty.
  - **Evidence:** `pd.concat([frame for frame in frames.values() if not frame.empty], ...)` in `reconforge/reconciliation/workorders.py`.
  - **Affected files:** `reconforge/reconciliation/workorders.py`.
  - **Technical risk:** A reconciliation with zero exceptions can crash instead of returning a stable empty result.
  - **Financial/operational risk:** Potential false pipeline stops in cleanly reconciled periods.
  - **Recommended fix:** Add guarded empty-frame fallback before concatenation.
  - **Implementation status:** Planned (in-progress).
  - **Tests required:** Regression test for fully-empty work-order exception result.
  - **Migration impact:** None.

- **Finding:** Evidence binder collection fails when no exception CSV files are present.
  - **Evidence:** `pd.concat` over candidate frames without empty-set guard in `reconforge/evidence/binder.py`.
  - **Affected files:** `reconforge/evidence/binder.py`.
  - **Technical risk:** Evidence generation can fail before report artifacts are written.
  - **Financial/operational risk:** Delays in evidence packaging and review readiness checks.
  - **Recommended fix:** Return empty case list when no candidate files exist, then still emit an empty but complete evidence package.
  - **Implementation status:** Planned (in-progress).
  - **Tests required:** Regressions for empty evidence input path.
  - **Migration impact:** None.

### Medium

- **Finding:** Financial parsing utilities return `float`; precision-sensitive controls are still vulnerable to rounding artifacts.
  - **Evidence:** `parse_amount()` and `round_money()` in `reconforge/utils/money.py`.
  - **Affected files:** `reconforge/utils/money.py`, `reconforge/reconciliation/stock_gl.py`, related call sites.
  - **Technical risk:** Non-deterministic equality boundaries for strict controls at edge precision cases.
  - **Financial/operational risk:** Minor mismatches in tolerance-sensitive matching and risk scoring.
  - **Recommended fix:** Introduce explicit decimal-backed value type and make tolerance/comparison behavior currency-aware and deterministic.
  - **Implementation status:** Not started.
  - **Tests required:** Precision-focused parser, matching, and tolerance tests.
  - **Migration impact:** Moderate; requires API compatibility review for helper functions and report serialization.

- **Finding:** `reconforge/platform` matching service uses greedy per-row selection with local tie preference.
  - **Evidence:** Candidate scan + one-pass `_best_candidate` in `reconforge/platform/matching.py`.
  - **Affected files:** `reconforge/platform/matching.py`.
  - **Technical risk:** Sub-optimal global assignment and potential row-order-dependent outcomes under ambiguity.
  - **Financial/operational risk:** Inconsistent audit trails when multiple viable matches exist.
  - **Recommended fix:** Introduce global optimization mode (same assignment strategy used by stock-to-GL matching) with deterministic tie-break rules.
  - **Implementation status:** Not started.
  - **Tests required:** Ambiguity and shuffle-invariance tests for platform matching service.
  - **Migration impact:** None (internal behavior change with improved determinism).

### Low

- **Finding:** Platform architecture, persistence abstraction, and CI hardening targets are partially defined but not consistently surfaced as ADR-backed state.
  - **Evidence:** No `docs/adr` lifecycle for the new platform direction in inspected files; required audit docs are missing.
  - **Affected files:** `docs/`, `docs/architecture/`.
  - **Technical risk:** Architectural drift and inconsistent team interpretation.
  - **Financial/operational risk:** Reduced auditability and slower onboarding for contributors.
  - **Recommended fix:** Establish baseline architecture/state artifacts and a staged roadmap for cross-module refactors.
  - **Implementation status:** In-progress (documentation bootstrap in this turn).
  - **Tests required:** None.
  - **Migration impact:** None.

### Enhancement

- **Finding:** No single baseline document exists for architecture state, target architecture, risk register, and roadmap aligned to this objective.
  - **Evidence:** Missing files under `docs/engineering-audit.md` and `docs/architecture/{current-state,target-state}.md`, `docs/roadmap.md`, `docs/risk-register.md`.
  - **Affected files:** `docs/`.
  - **Technical risk:** Incomplete baseline for subsequent phases.
  - **Financial/operational risk:** Reduced ability to verify phase-gated improvements.
  - **Recommended fix:** Maintain these files and refresh at each major phase.
  - **Implementation status:** In-progress.
  - **Tests required:** None.
  - **Migration impact:** None.
