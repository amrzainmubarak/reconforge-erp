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

- **Status:** In Progress (platform matching flow now min-cost assignment with deterministic candidate ordering; broader cross-module parity continues)
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

## R-005: Invalid platform amount values can be interpreted as numeric zero

- **Status:** Mitigated in platform matching.
- **Likelihood:** Medium
- **Impact:** High
- **Description:** Rows with malformed amount fields were previously normalized to `0.0`, allowing deterministic matching to produce false matches.
- **Owner:** Platform reconciliation maintainer
- **Controls:** Strict amount parsing in matching candidate build and score paths; unmatched status for invalid records.
- **Residual risk:** Low after strict parsing change; add broader dataset-type-specific validation before wider rollout.

## R-006: Duplicate or structurally identical rows without explicit IDs can still challenge stable fallback IDs

- **Status:** Open.
- **Likelihood:** Low.
- **Impact:** Medium.
- **Description:** For identical records lacking stable identifiers, deterministic fallback suffixing still uses canonical grouping order and may require explicit source keys for audit-perfect traceability.
- **Owner:** Platform matching maintainer.
- **Controls:** Recommend upstream source ID mapping, or future schema migration to include source-side deterministic record keys.
- **Residual risk:** Medium until deterministic lineage model is standardized in schema and API contracts.
