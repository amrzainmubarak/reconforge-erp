# Risk Register

## R-001: Empty-exception aggregation crash

- **Status:** Open (patched during this turn in `workorders` and `evidence` paths).
- **Likelihood:** Medium
- **Impact:** High
- **Description:** `pd.concat` on empty frame list can raise and break report/evidence steps.
- **Owner:** Reconciliation module maintainer
- **Controls:** Guard before concatenation and return deterministic empty outputs.
- **Residual risk:** Low after guard tests.

## R-002: Matching non-determinism across engines

- **Status:** Open
- **Likelihood:** Medium
- **Impact:** High
- **Description:** Platform matching implementation still uses greedy selection and may vary by row order under ambiguity.
- **Owner:** Matching subsystem maintainer
- **Controls:** Replace greedy with optimization-based assignment mode and property-based order tests.
- **Residual risk:** Medium until additional strategy rollout.

## R-003: Monetary precision drift

- **Status:** Open
- **Likelihood:** Medium
- **Impact:** Medium
- **Description:** Float-based values remain in several control and scoring paths.
- **Owner:** Data model and finance controls maintainer
- **Controls:** Introduce shared decimal value type with configured precision and strict parsing policy.
- **Residual risk:** Medium until all critical codepaths migrate.

## R-004: Evidence packaging quality when no exceptions exist

- **Status:** Open (patched during this turn in evidence collection).
- **Likelihood:** Medium
- **Impact:** Medium
- **Description:** Evidence flows can fail before index generation if high-risk candidate files are absent.
- **Owner:** Evidence module maintainer
- **Controls:** Explicit empty-case handling and manifest generation from available files.
- **Residual risk:** Low after this patch.
