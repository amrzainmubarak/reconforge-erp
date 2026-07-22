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

None newly identified in this phase.

### High

- **Finding:** Platform match jobs could include invalid numeric amounts via zero fallback.
  - **Evidence:** `reconforge/platform/common.py` exposed permissive converters and `reconforge/platform/matching.py` reused `to_float` for candidate indexing/scoring.
  - **Affected files:** `reconforge/platform/matching.py`, `reconforge/platform/common.py`.
  - **Technical risk:** Invalid amounts can appear as zero and be matched incorrectly.
  - **Financial/operational risk:** False-positive matches and hidden data-quality failures in platform-led workflows.
  - **Recommended fix:** Reject invalid numeric values from candidate consideration and treat them as unmatched with explicit exceptions.
  - **Implementation status:** Fixed in this phase.
  - **Tests required:** Invalid numeric amount regression test and row-order invariance checks.
  - **Migration impact:** Minimal; match behavior changes only for previously-invalid rows.

- **Finding:** Platform matching CLI and engine did not support an explicit many-to-many matching policy and fallback identifiers were coupled to row position.
  - **Evidence:** `reconforge/platform/matching.py` and `reconforge/cli.py` lacked `allow_many_to_many` mode and stable deterministic fallback identifier handling.
  - **Affected files:** `reconforge/platform/matching.py`, `reconforge/cli.py`, `tests/test_platform_matching.py`.
  - **Technical risk:** Ambiguous split/journal reconciliations could not be represented consistently.
  - **Financial/operational risk:** Reproducibility and auditability gaps in workflows that require many-to-many matching.
  - **Recommended fix:** Add policy-aware matching mode and deterministic identifier materialization from business keys when explicit IDs are absent.
  - **Implementation status:** In progress.
  - **Tests required:** Many-to-many and stable-ID regression tests.
  - **Migration impact:** Low; only matching output and IDs for missing explicit identifiers can shift.

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

- **Finding:** `reconforge/platform` matching service used a greedy per-row flow with local tie preference.
  - **Evidence:** Older versions of `reconforge/platform/matching.py` used row-order dependent candidate selection.
  - **Affected files:** `reconforge/platform/matching.py`.
  - **Technical risk:** Sub-optimal global assignment and potential row-order-dependent outcomes under ambiguity.
  - **Financial/operational risk:** Inconsistent audit trails when multiple viable matches exist.
  - **Recommended fix:** Introduce global optimization mode (same assignment strategy used by stock-to-GL matching) with deterministic tie-break rules.
  - **Implementation status:** In progress.
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

### Medium

- **Finding:** Cross-engine parity between pandas and DuckDB previously relied on aggregate counts only.
  - **Evidence:** `test_duckdb_and_pandas_engines_make_equivalent_reconciliation_decisions` previously asserted only row counts and summary equality.
  - **Affected files:** `tests/test_generator_benchmark_engines.py`, `reconforge/engines/base.py`, `reconforge/engines/pandas_engine.py`, `reconforge/engines/duckdb_engine.py`, `reconforge/engines/signature.py`.
  - **Technical risk:** Subtle non-deterministic or ordering differences could pass aggregate checks but diverge at row level.
  - **Financial/operational risk:** Inaccurate comparability claims could mask reconciliation decision differences.
  - **Recommended fix:** Add deterministic reconciliation signatures over match/exception rows and assert equality in parity test.
  - **Implementation status:** Implemented.
  - **Tests required:** Parity signature test (installed and executed when DuckDB is available).
  - **Migration impact:** None.

- **Finding:** Reference normalization for matching lacked explicit regression coverage in platform matching.
  - **Evidence:** `_normalize_reference` was introduced but not systematically validated in platform matching tests.
  - **Affected files:** `reconforge/platform/matching.py`, `tests/test_platform_matching.py`.
  - **Technical risk:** Reference cleanup changes could silently alter match outcomes without guardrails.
  - **Financial/operational risk:** Hidden false negatives in matching due formatting drift between source systems.
  - **Recommended fix:** Add deterministic reference normalization test cases and keep normalized/ raw values visible in explanations.
  - **Implementation status:** In progress (implemented with regression tests).
  - **Tests required:** Matching cases with separators/case/zero-padding variations.
  - **Migration impact:** Minimal.

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
