# Phase 3 External Evidence Gate Index (Current Status: In Progress / Engaged)

## Gate P3-EXT-001 (3–5 controlled pilots)

- Status: `engaged`
- Evidence target count: 3–5
- Required records:
  - [Pilot-001](./P3_EXT_001_PILOT_001.md) `status: completed` (local bounded run, not external)
  - [Pilot-002](./P3_EXT_001_PILOT_002.md) `status: completed` (local bounded run, not external)
  - [Pilot-003](./P3_EXT_001_PILOT_003.md) `status: completed` (local bounded run, not external)
  - (optional Pilot-004)
  - (optional Pilot-005)
- Evidence format:
  - `docs/execution/P3_EXT_001_PILOT_###.md`
  - Must be completed with `P3_EXT_001_CONTROLLED_PILOT_EVIDENCE_TEMPLATE.md`.

## Gate P3-EXT-002 (Independent security review)

- Status: `engaged`
- Evidence target:
  - Single independent review record
- Evidence format:
  - [Independent review report](./P3_EXT_002_REVIEW_REPORT.md) `status: pending`
  - Must be completed with `P3_EXT_002_INDEPENDENT_SECURITY_REVIEW_TEMPLATE.md`.

## Completion condition for both gates

- Both gates are **not complete** until:
  1. Evidence files exist.
  2. Findings and residuals are bounded and linked to concrete artifacts.
  3. `P3-EXT-001` contains only non-simulated, authorized, externally scoped records for publication decisions.
  4. The `BACKLOG`/`STATE`/`PHASE_1_3_EXECUTION_MATRIX` references are updated.

## Notes

- Keep this index as the only index of external evidence evidence in progress.
- For publication-safe verification, `P3-EXT-001` and `P3-EXT-002` must only be closed with non-simulated external evidence.
