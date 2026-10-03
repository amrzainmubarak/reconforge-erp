# Issue Pack Template — Per Slice Release Closure

## Copy this block for each open Slice

```markdown
### [ISSUE] [Slice ID] — [Slice Title]

**Priority:** [P0/P1/P4]  
**Area:** [container/matching/finance/iam/connectors/deployment/operations/platform]  
**Current status:** [blocked/in_progress/planned/deferred]  
**Owner:** [Team / Name]  
**ETA:** [YYYY-MM-DD]  
**Due gate:** [A/B/C/D/E/F]

#### Evidence (Authoritative references)

- `docs/execution/BACKLOG.yaml` (`[Slice ID]`)
- `docs/execution/STATE.md`
- `docs/execution/EVIDENCE.md`
- `docs/execution/CLAIMS_EVIDENCE_MATRIX.md`
- `docs/execution/GAP_MATRIX.md`
- `docs/execution/DEPLOYMENT_READINESS_MATRIX.v1.yaml`
- `docs/execution/DEPENDENCY_RISK.md`
- `docs/execution/BASELINE.md`
- `docs/execution/SECURITY_BASELINE.md`
- `docs/execution/QUALITY_BASELINE.md`

#### Acceptance Criteria

- [ ] Evidence chain complete for this slice (code / test / runtime)
- [ ] Exit condition explicit in BACKLOG and mapped in STATE
- [ ] No claim drift (claims only as bounded/local if evidence is bounded/local)
- [ ] No unresolved critical/high blocker inherited from earlier gates
- [ ] Risk/retry/rollback path documented

#### Planned Evidence Commands

- `python -m pytest` (or exact focused suite path)
- `python -m ruff check .`
- `python -m mypy reconforge`
- `python -m build --no-isolation` (if release/dependency scope changes)
- `python -m pip_audit`
- Docker/HA-DR/profiler command specific to slice (if applicable)

#### Definition of Done for this slice

- [ ] Slice state in `BACKLOG.yaml` updated to `completed` (or intentionally deferred with written rationale)
- [ ] Dashboard updated (No-Go / RAG status / owner / acceptance)
- [ ] Evidence references updated and check-linked
- [ ] Blocker path documented in `GLOBAL_PROFESSIONAL_PRE_MERGE_GATE.md` when applicable
```

## Ready-to-use Open Issues (current context as of latest snapshot)

1. **`E-824`** — Remediate or independently disposition current exact-image High findings  
   - Priority: P0  
   - Current state: `blocked`  
   - Gate: A  
   - Owner: Container/Release

2. **`E-1000`** — Define and run the Global Expansion Execution Track  
   - Priority: P0  
   - Current state: `in_progress`  
   - Gate: B  
   - Owner: Product/Architecture

3. **`E-1001`** — Establish global expansion execution slices  
   - Priority: P0  
   - Current state: `in_progress`  
   - Gate: B/C  
   - Owner: Architecture

4. **`E-1002`** — Complete global-ready close/consolidation evidence closure  
   - Priority: P0  
   - Current state: `in_progress`  
   - Gate: C  
   - Owner: Finance Platform

5. **`E-1003`** — Complete deterministic, reproducible advanced matching evidence package  
   - Priority: P0  
   - Current state: `in_progress`  
   - Gate: C  
   - Owner: Matching

6. **`E-1004`** — Govern write-back with replayable compensation and provider-neutral transport hardening  
   - Priority: P0  
   - Current state: `in_progress`  
   - Gate: C/E  
   - Owner: Connectors/Security

7. **`E-1005`** — Expand enterprise governance primitives (RBAC + ABAC + SoD)  
   - Priority: P0  
   - Current state: `in_progress`  
   - Gate: E  
   - Owner: IAM/Governance

8. **`E-884`** — Gate Python 3.12 Alpine base-image upgrade behind matrix evidence  
   - Priority: P1  
   - Current state: `planned`  
   - Gate: D  
   - Owner: Platform/Release

9. **`E-1006`** — Produce mode-specific deployment-readiness evidence  
   - Priority: P1  
   - Current state: `in_progress`  
   - Gate: D  
   - Owner: Deployment

10. **`E-1007`** — Add fail-closed deployment edition profile contract  
    - Priority: P1  
    - Current state: `in_progress`  
    - Gate: D  
    - Owner: Deployment/Security

11. **`P4-FIN-002`** — Governed close and full consolidation lifecycle  
    - Priority: P4  
    - Current state: `in_progress`  
    - Gate: C/E/F  
    - Owner: Finance Platform

12. **`P4-CON-001`** — Live ERP and banking connectors with governed write-back  
    - Priority: P4  
    - Current state: `in_progress`  
    - Gate: C/E/F  
    - Owner: Connectors

13. **`P4-SCL-001`** — High-volume concurrent operations and backpressure  
    - Priority: P4  
    - Current state: `in_progress`  
    - Gate: D/E/F  
    - Owner: Operations/Backend

14. **`P4-REL-001`** — High-availability and disaster recovery  
    - Priority: P4  
    - Current state: `in_progress`  
    - Gate: D/F  
    - Owner: SRE/Infra

15. **`P4-IAM-001`** — Complex enterprise authorization and policy administration  
    - Priority: P4  
    - Current state: `in_progress`  
    - Gate: E/F  
    - Owner: IAM/Platform

16. **`P4-PLAT-001`** — Coherent modular platform breadth  
    - Priority: P4  
    - Current state: `in_progress`  
    - Gate: E/F  
    - Owner: Platform Engineering
