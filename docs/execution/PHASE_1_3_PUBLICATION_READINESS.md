# Phase 1-3 Owner/Team Publication Readiness

> Governing decision: E-251 / D236. The repository owner and project team are
> the release authority. External operators and an independent security review
> are optional assurance items and do not block a team-controlled publication.

## 1) Required scope

- Required non-P0 tasks: `41/41` completed.
- Phase 1 required tasks: `10/10` completed.
- Phase 2 required tasks: `18/18` completed.
- Phase 3 required tasks: `13/13` completed.
- Required phase gates: verified from retained code, test, runtime, build,
  migration, restore, security, deterministic-replay, and operational evidence.
- Release authority: repository owner and authorized project team.

`P3-EXT-001` and `P3-EXT-002` are retained as `optional_assurance` items with
`deferred` status. No accountant, external operator, profession-specific
participant, or independent reviewer is required for this release policy.

## 2) Required pre-publication gates

Run on the exact candidate commit:

- `python -m ruff check .`
- `python -m mypy reconforge`
- `python -m pytest`
- `python -m bandit -q -r reconforge`
- `python -m pip_audit`
- `python -m build --no-isolation`
- `git diff --check`
- `npm --prefix apps/web ci`
- `npm --prefix apps/web run typecheck`
- `npm --prefix apps/web run test:run`
- `npm --prefix apps/web run build`
- `npm --prefix apps/web run e2e`
- `python -m pytest tests/test_phase_1_3_execution_contract.py`
- `python -m pytest tests/test_phase_1_exit_audit.py tests/test_phase_2_exit_audit.py`

Publishing also requires a clean worktree, reviewed release diff, rollback plan,
and green required GitHub checks on the published candidate. A failed required
technical gate, a known unaccepted Critical/High vulnerability, or a dirty
release tree remains a hard blocker.

## 3) Optional assurance

- External public-data pilots may be collected later under `P3-EXT-001`.
- An independent security review may be commissioned later under `P3-EXT-002`.
- These items can support only the extra claims their evidence proves. Their
  absence does not block owner/team publication.
- Internal or automated evidence must never be relabeled as customer evidence,
  an independent review, certification, or compliance assessment.

## 4) Claim boundary

Publication may describe only the bounded features and measurements present in
`CLAIMS_EVIDENCE_MATRIX.md`. The following remain prohibited without separate
evidence:

- universal superiority or "best in the world";
- unqualified `Enterprise-ready` or `Bank-grade`;
- certification or compliance claims;
- customer, external-pilot, or independent-review claims;
- scale, SLO, HA, DR, provider, or interoperability claims outside the measured
  environments.

## 5) Decision rule

- **Go:** exact candidate passes every required local and GitHub gate; owner/team
  approves the diff, wording, version, and rollback plan.
- **No-Go:** any required technical gate fails, a release blocker is unresolved,
  the candidate differs from the tested commit, or public wording exceeds the
  evidence matrix.

Optional external assurance status does not change this decision rule.
