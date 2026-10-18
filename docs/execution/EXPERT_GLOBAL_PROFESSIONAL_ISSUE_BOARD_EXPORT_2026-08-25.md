# Issue Board Export — Professional Readiness Gaps (2026-08-25)

> Use this file to paste tasks directly into your issue tracker. Each block is
> scoped to evidence-backed acceptance and mapped to the existing execution
> artifacts in `docs/execution`.

## [ISSUE] `E-824` — Remediate exact-image security blocker (CVE-2026-14456)

- **Priority:** P0
- **Area:** container/security
- **Current status:** blocked
- **Owner:** Container/Release
- **Due:** Day 1
- **Due gate:** A
- **Evidence refs:**
  - `docs/execution/DEPENDENCY_RISK.md`
  - `docs/execution/BASELINE.md`
  - `docs/execution/SECURITY_BASELINE.md`

### Acceptance Criteria
- [ ] Rebuild exact image with OpenSSL 3.5.8+ (or approved governed equivalent disposition).
- [ ] Re-run exact image dependency/security checks with aligned scanner output (no conflicting tool discrepancy).
- [ ] `E-824` in `docs/execution/BACKLOG.yaml` moved to `completed`.
- [ ] SBOM / VEX / signature / reproducibility paths updated and linked in evidence files.

### Required Evidence Commands
- `docker build` (exact release image path)
- Exact-image vulnerability scan path used by project (documented in `DEPENDENCY_RISK.md`)
- `python -m pip_audit`
- SBOM generation and VEX verification commands used by gate

### Definition of Done
- No High/Critical blocker remains open for release gate.
- `GLOBAL_PROFESSIONAL_EXECUTION_DASHBOARD.md` and `EVIDENCE.md` updated.
- `docs/execution/QUALITY_BASELINE.md` updated where required.

## [ISSUE] `E-1000` — Define and run Global Expansion execution track

- **Priority:** P0
- **Area:** architecture/claims
- **Current status:** in_progress
- **Owner:** Product/Architecture
- **Due:** Days 3–4
- **Due gate:** B
- **Evidence refs:** `docs/adr/0531-global-expansion-program-framework.md`, `docs/execution/CLAIMS_EVIDENCE_MATRIX.md`, `docs/execution/STATE.md`, `docs/execution/BACKLOG.yaml`

### Acceptance Criteria
- [ ] Closed claim-boundary definitions for all globally claimed slices.
- [ ] Remove/relift unsupported global wording to bounded/local-only phrasing.
- [ ] `E-1000` exit condition explicitly recorded in `STATE.md` and `BACKLOG.yaml`.

## [ISSUE] `E-1001` — Establish global expansion slice orchestration

- **Priority:** P0
- **Area:** architecture/program-management
- **Current status:** in_progress
- **Owner:** Architecture
- **Due:** Days 3–4
- **Due gate:** B/C
- **Evidence refs:** `docs/execution/BACKLOG.yaml`, `docs/execution/STATE.md`, `docs/execution/GAP_MATRIX.md`

### Acceptance Criteria
- [ ] All dependent slices in integrity/matching/connectors/identity/deployment are status-closed per dependencies.
- [ ] No claim-boundary drift after closure.
- [ ] Dependency graph in backlog reflects valid and explicit execution order.

## [ISSUE] `E-1002` — Close global-ready close/consolidation evidence

- **Priority:** P0
- **Area:** finance/reconciliation
- **Current status:** in_progress
- **Owner:** Finance Platform
- **Due:** Day 5
- **Due gate:** C
- **Evidence refs:** `docs/execution/GAP_MATRIX.md`, `docs/execution/BACKLOG.yaml`, `docs/execution/EVIDENCE.md`

### Acceptance Criteria
- [ ] lock/reopen/rollback/restore behavior proven via evidence artifacts.
- [ ] replayable proof for closing lifecycle.
- [ ] no partial close leak across modes.

## [ISSUE] `E-1003` — Finish deterministic matching parity and ambiguity policy

- **Priority:** P0
- **Area:** matching
- **Current status:** in_progress
- **Owner:** Matching
- **Due:** Day 6
- **Due gate:** C
- **Evidence refs:** `docs/execution/CLAIMS_EVIDENCE_MATRIX.md`, `docs/execution/STATE.md`

### Acceptance Criteria
- [ ] Cross-engine + cross-host determinism evidence recorded.
- [ ] permutation/reproducibility evidence and policy for unresolved ambiguity exists.
- [ ] tie-break and complexity limit rules are documented and enforced.

## [ISSUE] `E-1004` — Govern write-back with replayable compensation

- **Priority:** P0
- **Area:** connectors/security
- **Current status:** in_progress
- **Owner:** Connectors/Security
- **Due:** Day 7
- **Due gate:** C/E
- **Evidence refs:** `docs/execution/GAP_MATRIX.md`, `docs/execution/BACKLOG.yaml`

### Acceptance Criteria
- [ ] Read/write split enforced and documented.
- [ ] replay/compensation proof for write actions.
- [ ] provider-neutral transport hardening proven.
- [ ] `E-1004` and dependent claims cannot be claimed production-safe without full conformance.

## [ISSUE] `E-1005` — Expand enterprise governance primitives (RBAC + ABAC + SoD)

- **Priority:** P0
- **Area:** IAM/governance
- **Current status:** in_progress
- **Owner:** IAM/Governance
- **Due:** Day 6
- **Due gate:** E
- **Evidence refs:** `docs/execution/STATE.md`, `docs/execution/EVIDENCE.md`, `docs/execution/GAP_MATRIX.md`

### Acceptance Criteria
- [ ] No self-approval path for high-risk objects.
- [ ] policy conflict detection for actor/role conditions is present.
- [ ] high-risk audit routes explicitly linked to evidence graph.

## [ISSUE] `E-884` — Python 3.12 Alpine base migration + rollback evidence

- **Priority:** P1
- **Area:** platform/release
- **Current status:** planned
- **Owner:** Platform/Release
- **Due:** Day 2
- **Due gate:** D
- **Evidence refs:** `docs/execution/QUALITY_BASELINE.md`, `docs/execution/SECURITY_BASELINE.md`, `docs/execution/BASELINE.md`

### Acceptance Criteria
- [ ] New base image builds and runtime behavior validated.
- [ ] rollback path tested and documented.
- [ ] dependency/security scans repeated and linked to updated evidence.

## [ISSUE] `E-1006` — Produce mode-specific deployment-readiness evidence

- **Priority:** P1
- **Area:** deployment
- **Current status:** in_progress
- **Owner:** Deployment
- **Due:** Day 8
- **Due gate:** D
- **Evidence refs:** `docs/execution/DEPLOYMENT_READINESS_MATRIX.v1.yaml`, `docs/execution/STATE.md`, `docs/execution/BACKLOG.yaml`

### Acceptance Criteria
- [ ] community/team/enterprise/regulated manifests/runbooks updated with proof.
- [ ] each mode includes rollback and verification evidence.
- [ ] no unverified mode launch claims.

## [ISSUE] `E-1007` — Add fail-closed edition profile contract

- **Priority:** P1
- **Area:** deployment/security
- **Current status:** in_progress
- **Owner:** Deployment/Security
- **Due:** Days 8–9
- **Due gate:** D
- **Evidence refs:** `docs/execution/STATE.md`, `docs/execution/BACKLOG.yaml`

### Acceptance Criteria
- [ ] Edition contract rejects incomplete profiles by default.
- [ ] claim digest check integrated to prevent unsafe mode launch.
- [ ] remediation path for failures exists and is tested.

## [ISSUE] `P4-FIN-002` — Governed close and full consolidation lifecycle

- **Priority:** P4
- **Area:** finance/platform
- **Current status:** in_progress
- **Owner:** Finance Platform
- **Due:** Days 11–14
- **Due gate:** C/E/F
- **Evidence refs:** `docs/execution/GAP_MATRIX.md`, `docs/execution/STATE.md`, `docs/execution/BACKLOG.yaml`

### Acceptance Criteria
- [ ] statutory/legal/equity/intercompany/restore boundaries covered.
- [ ] migration/restore and rollback behaviors tested.
- [ ] no unsupported production close claim survives in documentation.

## [ISSUE] `P4-CON-001` — Live connectors with governed write-back

- **Priority:** P4
- **Area:** connectors/operations
- **Current status:** in_progress
- **Owner:** Connectors
- **Due:** Days 9–14
- **Due gate:** C/E/F
- **Evidence refs:** `docs/execution/GAP_MATRIX.md`, `docs/execution/BACKLOG.yaml`, `docs/execution/STATE.md`

### Acceptance Criteria
- [ ] live connector idempotency and cursor behavior proven.
- [ ] retry/backoff/recovery and audit trails present.
- [ ] no write-back without compensation path.

## [ISSUE] `P4-SCL-001` — High-volume operations, backpressure, and durable jobs

- **Priority:** P4
- **Area:** operations/backend
- **Current status:** in_progress
- **Owner:** Operations/Backend
- **Due:** Days 11–14
- **Due gate:** D/E/F
- **Evidence refs:** `docs/execution/STATE.md`, `docs/execution/BACKLOG.yaml`

### Acceptance Criteria
- [ ] soak/perf benchmarks executed at declared size tier and repeatable.
- [ ] no duplicate effects under concurrency.
- [ ] bounded cancellation/backpressure/retry behavior documented.

## [ISSUE] `P4-REL-001` — High-availability and disaster recovery

- **Priority:** P4
- **Area:** sre/infra
- **Current status:** in_progress
- **Owner:** SRE/Infra
- **Due:** Days 11–14
- **Due gate:** D/F
- **Evidence refs:** `docs/execution/STATE.md`, `docs/execution/BACKLOG.yaml`, `docs/execution/GAP_MATRIX.md`

### Acceptance Criteria
- [ ] RPO/RTO drills repeated on at least 2 runs.
- [ ] recovery and failback runbook evidence.
- [ ] documented evidence of operation outside single-host assumptions.

## [ISSUE] `P4-IAM-001` — Complex authorization, policy admin, and policy exceptions

- **Priority:** P4
- **Area:** iam/platform
- **Current status:** in_progress
- **Owner:** IAM/Platform
- **Due:** Days 11–14
- **Due gate:** E/F
- **Evidence refs:** `docs/execution/STATE.md`, `docs/execution/BACKLOG.yaml`

### Acceptance Criteria
- [ ] delegation, emergency and cache invalidation paths are controlled and logged.
- [ ] complete exception audit trace for policy bypass decisions.
- [ ] no self-approval or overbroad grant path accepted.

## [ISSUE] `P4-PLAT-001` — Coherent modular platform breadth

- **Priority:** P4
- **Area:** platform/architecture
- **Current status:** in_progress
- **Owner:** Platform Engineering
- **Due:** Days 11–14
- **Due gate:** E/F
- **Evidence refs:** `docs/execution/GAP_MATRIX.md`, `docs/execution/BACKLOG.yaml`, `docs/execution/STATE.md`

### Acceptance Criteria
- [ ] All required bounded contexts have manifest/adapter/migration + rollback evidence.
- [ ] Tests updated for manifest-complete states.
- [ ] no context remains claimed stable without completion evidence.

