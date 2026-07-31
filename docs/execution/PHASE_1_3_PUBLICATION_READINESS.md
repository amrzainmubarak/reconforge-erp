# Phase 1-3 Publication Readiness Checklist

> Status at generation time: `docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml` remains
`all_tasks_completed: false` and `all_required_gates_verified: false` until external gates are fulfilled.

## 1) External gates that must be closed first

1. **P3-EXT-001 — Real controlled pilots (3–5)**
   - Evidence files: add in `docs/execution/` at least three pilot records with environment, data authorization, workflow, outcomes, failures, user feedback, and allowed wording.
   - Pilot record template: `docs/execution/P3_EXT_001_CONTROLLED_PILOT_EVIDENCE_TEMPLATE.md`
   - Evidence index: `docs/execution/P3_EXTERNAL_GATE_EVIDENCE_INDEX.md`
   - Required status in matrix: `external_gate_policy.gates.p3_external_pilots.status = verified`.
   - Required evidence list in matrix/task state:
      - `completed_slices` for `P3-ENT-013` must include one bounded, de-identified pilot evidence map.
   - Guard to re-check:
     - `P3-ENT-013` cannot be set `completed` before this is verified.

2. **P3-EXT-002 — Independent security review**
   - Evidence files: add named reviewer identity, scope, date, findings, remediation status, and residual-risk acceptance.
   - Review template: `docs/execution/P3_EXT_002_INDEPENDENT_SECURITY_REVIEW_TEMPLATE.md`
   - Evidence index: `docs/execution/P3_EXTERNAL_GATE_EVIDENCE_INDEX.md`
   - Required status in matrix: `external_gate_policy.gates.p3_independent_security_review.status = verified`.
   - Scope must remain explicit:
     - no certified/compliance/production-claims without independent evidence.

## 2) Internal blockers before publish

Keep these as hard blockers even after external gates:

- `P3-ENT-013` remains an internal blocker:
  - `P3-ENT-013` is publication-safe only after bounded pilot + security-gate verification.
- `P3-ENT-013` must remain dependent on:
  - completion of its published competitive evidence mapping,
  - both external gates above.
- `P3-ENT-013` should only close after publication-safe competitive matrix evidence is complete and bounded.

## 3) Release readiness commands (exact minimum for final gating pass)

Re-run before final claim:

- Python:
  - `python -m ruff check .`
  - `python -m mypy reconforge`
  - `python -m pytest`
  - `python -m bandit -q -r reconforge`
  - `python -m pip_audit`
  - `python -m build --no-isolation`
  - `git diff --check`
- Web:
  - `npm --prefix apps/web ci`
  - `npm --prefix apps/web run typecheck`
  - `npm --prefix apps/web run test:run`
  - `npm --prefix apps/web run build`
- Release contract tests:
  - `python -m pytest tests/test_phase_1_3_execution_contract.py`
  - `python -m pytest tests/test_phase_1_exit_audit.py`
  - `python -m pytest tests/test_phase_2_exit_audit.py`

## 4) Pre-publish hard gates (must be true before PR merge/push)

1. Update `docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml`:
   - `all_tasks_completed: true`
   - `all_required_gates_verified: true`
   - both external gates status to `verified`
   - evidence references in `completed_slices` and `external_gate_policy.evidence_artifacts` are current.
2. Re-open `docs/execution/STATE.md` for the same state with no stale historical-only blocker notes.
3. Re-open `docs/execution/EVIDENCE.md` and keep historical rerun failures only as historical context (non-blocking), with current successful reruns explicitly present.
4. Re-run test: `tests/test_phase_1_3_execution_contract.py` and confirm
   `test_phase_three_has_no_unsupported_completion_shortcut` passes.
5. Confirm git/workspace conditions from AGENTS:
   - clean rationale for final branch,
   - no publication from dirty worktree,
   - explicit draft PR and rollback plan,
   - no unsupported marketing claims.

## 5) Publication decision

After all above are verified, set publication status as:

- **No-Go**: if any one item above is missing or stale.
- **Go**: only when external pilots, independent security review, and matrix closure are all recorded as deterministic evidence and command gates are green.
