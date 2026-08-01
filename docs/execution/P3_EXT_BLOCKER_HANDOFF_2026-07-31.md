# P3 External Blocker Handoff (Plan 1–3 Completion Gate)

> Archived historical handoff. External pilots and independent review were
> reclassified as deferred optional assurance by E-251/D236 and no longer block
> owner/team publication.

Date: 2026-07-31
Branch: feature/phase123-exec-restart

## Objective status (authoritative)

Current status from live files:

- `docs/execution/BACKLOG.yaml`: 62 tasks completed, 3 tasks `in_progress`.
- `docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml`: `phase_3` has 12/15 completed.
- `tests/test_phase_1_3_execution_contract.py::test_phase_three_has_no_unsupported_completion_shortcut` fails by design because:
  - `closure_policy.all_tasks_completed` is `false`.
  - `closure_policy.all_required_gates_verified` is `false`.

This is a hard publication gate, not an implementation defect.

> Note on the user objective wording:
>
> The requested “6 tasks” correspond to two layers:
> 1) 3 platform execution tasks currently `in_progress` in `BACKLOG.yaml`.
> 2) 3 external closeout actions (pilot set + review evidence package) required by `P3-EXT-001`/`P3-EXT-002` gates.
> Total closeout dependency count remains 6 expected outputs before publication-safe exit, but only 3 are represented as open task IDs in backlog.

## Open in-scope tasks (as currently persisted)

1) `P3-ENT-013` — Evidence-based competitive capability assessment  
   - File: `docs/execution/P3_ENT_013_EXIT_AUDIT.yaml`
   - Gate evidence: `p3_competitive_evidence` is verified.
   - Blockers: depends on `p3_ext_pilot_dependency` and `p3_independent_review_dependency` (blocked).

2) `P3-EXT-001` — Three to five real controlled pilots  
   - File(s): `docs/execution/P3_EXT_001_PILOT_001.md`, `..._002.md`, `..._003.md`
   - Current state: completed internally only (synthetic/local), not external real-pilot evidence.
   - Matrix gate status: `external_gate_policy.gates.p3_external_pilots.status = engaged`, no evidence artifacts.

3) `P3-EXT-002` — Independent security review  
   - File: `docs/execution/P3_EXT_002_REVIEW_REPORT.md`
   - Current state: pending external reviewer evidence.
   - Matrix gate status: `external_gate_policy.gates.p3_independent_security_review.status = engaged`, no evidence artifacts.

## External non-code outputs still required to claim completion of the 6-item user request

- `P3_EXT_001_PILOT_004.md` (or replacement pilot files) must be a real controlled external pilot; plus two additional external pilot records if counting a 3–5 range as separate closeout bullets.
- `P3_EXT_001_PILOT_005.md` (optional): third/fourth/fifth external pilot slot as needed.
- `P3_EXT_002_REVIEW_REPORT.md`: independent security review record signed by qualified external reviewer.
- Optional supporting annexes:
  - Reviewer CV/proof of qualification and COI declaration.
  - Retest logs evidencing remediation closure for any non-zero findings.
- All of the above must include authorization trail and non-synthetic evidence tags before they can be treated as publication-safe.

## Completion condition for final publication gate

To move from current state to publishable Phase 1–3 completion:

- `docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml`
  - set `closure_policy.all_tasks_completed = true`
  - set `closure_policy.all_required_gates_verified = true`
  - update `external_gate_policy.gates[].status = verified`
  - populate each gate `evidence_artifacts` with real file paths
- `docs/execution/P3_ENT_013_EXIT_AUDIT.yaml`:
  - set `status: verified`
  - mark `p3_ext_pilot_dependency` and `p3_independent_review_dependency` as verified
  - keep `publication_block` false only after evidence is attached
- Run final gates:
  - `python -m pytest tests/test_phase_1_exit_audit.py`
  - `python -m pytest tests/test_phase_2_exit_audit.py`
  - `python -m pytest tests/test_phase_1_3_execution_contract.py`
  - all must pass, including guard check in `test_phase_three_has_no_unsupported_completion_shortcut`
- Run UI/build security gates as already recorded:
  - `npm --prefix apps/web ci`
  - `npm --prefix apps/web run typecheck`
  - `npm --prefix apps/web run test:run`
  - `npm --prefix apps/web run build`
  - `npm --prefix apps/web run e2e`

## What must be provided (non-simulated)

- For `P3-EXT-001`:
  - 3–5 real controlled-pilot records using
    `docs/execution/P3_EXT_001_CONTROLLED_PILOT_EVIDENCE_TEMPLATE.md`
  - valid authorization trail (scope/date/approvals, no synthetic/local-only data claims)
- For `P3-EXT-002`:
  - qualified independent reviewer identity and scope
  - findings linked to evidence artifacts
  - remediation/remap and retest evidence
  - residual-risk acceptance by authorized human

When these files are attached, we can execute the final matrix closure and proceed with publication.
