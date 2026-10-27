# Prerequisite engineering assurance — 2026-10-26

**RELEASE BLOCKED. Program Q/S/U/P/I/R remain OPEN.** The prerequisite completion
matrix remains authoritative; this is bounded defect repair, not program acceptance.
No competitive superiority, production readiness, ISO certification or performance
advantage is asserted.

## Source and execution boundary

Primary checkout only: `F:\reconforge-erp`; one worktree; branch
`amr/assurance-prerequisite-repair-20261025`. Entry HEAD
`d487fc83fd243856ca671cdae4e2d6f9a633f499` already had101 changed/untracked files.
The local HEAD alone does not identify tested source. Its inherited patch and file
fingerprints are retained in `output/assurance-20261026/entry.patch` and
`entry-manifest.json`. Reviewed runtime source is identified by each command receipt's
before/after digest; a changed digest is explicitly diagnostic, not frozen acceptance.

Authenticated GitHub read confirms Draft PR143 remains on
`ff8a45cb0c2b3f9f6f7c657f65728b9c2dfb3b25`, with historical failed required checks.
It does not qualify local HEAD or current work. No main modification, merge,
production deployment, additional checkout or worktree occurred.

Three concurrent workstreams used exclusive files. QA authored independent defect
oracles; engineering/product/lead authored fixes and cross-reviewed them. Git/shared
migrations/integration remained lead-owned. Existing work and negative evidence are
preserved. See [ADR0871](../adr/0871-crm-quotation-provenance-and-workspace-lines.md).

## Defects and acceptance decisions

| Defect | Root cause / repair | Independent evidence | Decision |
| --- | --- | --- | --- |
| Stale verified financial/leave results after input edits | Existing request lifecycle did not receive form changes. All request-affecting edits now clear results/abort requests. | Product red oracles; QA54 focused passes; real English and Arabic browser journeys. | Bounded repair accepted; no human usability measurement inferred. |
| Capacity reschedule returns success without persistence or capacity validation in an existing transaction | Validation and writes were accidentally conditional on transaction initialization. Corrected indentation. | Independent2 red cases; engineering24 focused passes; QA25 capacity cases. | Repair accepted; existing repository commit semantics are unchanged. |
| CRM canonical author storage absent | API/repositories referenced an uncreated table. SQLite59 and PostgreSQL155 register parent-bound immutable provenance with no historical identity inference. | QA missing-table red; rename/legacy409 regression; restricted-role native authority gate. | Bounded repair accepted; earlier incomplete workflow claims remain withdrawn. |
| SQLite quotation lines cross workspace boundaries | Line PK/read/delete used quote ID alone. Added workspace key and deterministic legacy upgrade. | QA two-workspace same-ID100/900 red oracle. | Accepted for tested scope; collided/orphan legacy records refuse recovery without source evidence. |
| Partial SQLite59 upgrade after marker insertion failure | executescript implicitly committed schema before migration metadata. Owned statements, schema transformation and marker now share a transaction. | Independent injected marker failure red; full rollback/schema/row preservation green. | Repair accepted. |
| CRM repository construction commits unrelated caller work | executescript/commit escaped the caller's transaction. Nested savepoints preserve caller ownership. | Product original transaction oracle, QA rollback regression and engineering unique/collided constructor tests. | Repair accepted for construction; no blanket unit-of-work claim. |
| Restore oracle assumes global user IDs / single-tenant database | Module fixture retains multiple tenants; ID-only dicts collapse users. Scope binding count and composite tenant/user identity without omitting any table/row. | Native original failures retained; corrected full snapshot/restore/idempotent replay gate. | Test oracle corrected; no financial assertions removed. |
| Native tests not authoritative in configured CI | Unconfigured matrix would only skip new native proofs. Three full files now required in real PostgreSQL browser job with mandatory native admission. | Exact file ownership CI contract + independent QA8 cases. | Selection contract accepted; hosted execution still pending. |

## Engineering quality scorecard

These are measured contracts, not numerical product rankings or formal standard
conformance. The full ISO/IEC25010 assessment remains deferred until prerequisite
acceptance; subcharacteristics have not been represented as fully assessed.

| Quality area | Measurable bounded criterion | Result / limits |
| --- | --- | --- |
| Functional suitability | Independent workspace, money, provenance and reschedule oracles pass | Focused Python57pass/0skip; full declared ERP workflows remain incomplete. |
| Reliability | Injected migration failure leaves original schema/data/version; native restore/replay matches every row | Local migration and native cohort receipts; no HA/geographic DR claim. |
| Security | Canonical author immutable; real restricted-role foreign tenant/workspace writes/reads refused | Native authority test; no independent penetration-test claim. |
| Interaction/accessibility | Input edits clear verified results; delayed results refused; selected real Arabic390px RTL/Axe path passes | Browser2 journeys; no whole-app WCAG or human satisfaction claim. |
| Maintainability | Ruff/mypy/Bandit complete on tested source | Receipts identify exact scope; scanner results are not security certification. |
| Compatibility | Upgrade existing0154 to0155; legacy author remains unverified; empty down/up and populated refusal | Native migration tests; Community58→59 preserves uniquely owned legacy data. |
| Performance efficiency | No optimized financial control or equivalent before/after benchmark in this slice | UNMEASURED; command timings are verification durations, not throughput benchmarks. |
| Flexibility/adaptability | Existing Community/PostgreSQL paths preserved for corrected use cases | No broader deployment qualification inferred. |
| Safety | No stale verified values after request-affecting edits; no inferred legacy author approval | Tested scenarios only; no all-input defect-free claim. |

## Evidence and reproduction

Raw evidence is retained under `output/assurance-20261026/`. Each `lead-*.json`
receipt contains exact command, UTC start, elapsed duration, HEAD, source digests,
raw log path and SHA256. `environment.json` identifies the actual Windows,
Python3.12.13, Node/npm and PostgreSQL16.15 environment. JUnit retains per-test
outcomes. Original failures are never replaced by green results.

- `lead-focused-frozen`: Python57pass/0skip,25.110s; unchanged final source digest. Supported interpreter; focused business/security/transaction cohort. Earlier `lead-focused-final`24.719s remains retained.
- `lead-ci-contracts-corrected`:28pass/1skip (unconfigured native operations case). That skip is not native acceptance; its configured shard remains required.
- `lead-web-tests-final`:112 files/1241pass;101.484s. Whole-tree digest changed only while the unrelated CI-selection contract was corrected; do not call this frozen whole-source qualification.
- `lead-web-build-final`: production TypeScript/Vite build passes;5.062s.
- `lead-npm-ci`: clean locked install,161 audited packages, zero reported vulnerabilities;15.235s. This does not qualify all release artifacts.
- `lead-browser-final`:2pass/0retry;39.938s; real PostgreSQL/HTTPS/authentication/approval/posting, changed-input invalidation, Arabic mobile RTL/Axe. Stable digest `76ca4fdec7959f20760b2a929307ceef644a9ede04506b2e32eed251de874955`.
- `lead-native-acceptance`:17pass/0skip;198.422s; included complete native backup/restore, source replay, migration155, immutable authority/RLS. Whole-tree digest drift from CI-test editing is retained; successor frozen mandatory-native receipt is separate.
- `lead-native-frozen`:17pass/0skip/0xfail/0xpass;190.016s; mandatory native plugin; exit0 and unchanged whole-tree source digest `76ca4fdec7959f20760b2a929307ceef644a9ede04506b2e32eed251de874955`. Final authoritative receipt/JUnit for this bounded cohort.
- `lead-ruff-frozen`, `lead-mypy-final`, `lead-bandit-final`: full static checks. Bandit suppression warnings and Starlette httpx deprecation remain in raw logs.
- `lead-package-final`: source/wheel build passes;45.297s; unchanged source digest. Wheel bytes for the SQLite59 helper and PostgreSQL authority schema match source;0155 migration is included. Artifact hashes are retained in `package-hashes.json`; packaging success is not installation/container/release qualification.

The browser log retains Windows Proactor `ConnectionResetError10054` during
connection teardown despite both journeys passing. It is a residual operational
observation requiring triage; no clean-server-log assertion is made. No retries
were used to turn a failed run green. Prior harness/fixture artifacts were copied
to `preexisting-browser-*` before rebuilding, preserving earlier evidence.

## Remaining gates / risk register

1. Prerequisite matrix INCOMPLETE domains remain: governed CRM termination/refund,
   integrated manufacturing quality/stock/GL closure, leave-to-payroll/statutory
   integration and remaining whole-domain acceptance. These are not cosmetic gaps.
2. Final clean commit/hosted CI/security/exact-image/container/install/whole-schema
   recovery and source-bound release qualification are not all complete.
3. This slice does not rerun the entire Python regression, all Python versions,
   full E2E suite, all dependency/image scans, soak/chaos/mutation campaigns or
   production profiles. Earlier results remain bound to their own source.
4. External security assessment, domain/customer validation and real participant
   usability studies remain external requirements. No user satisfaction is invented.
5. Competitive capability research, fair benchmarks, differentiation and market
   ranking remain NOT TESTED because prerequisite release acceptance is open.

No final RC or program acceptance is issued. Changes remain reviewable in the
primary working directory alongside explicitly preserved inherited repairs;
no unrelated dirty files were silently included in a release commit.

The test-owned PostgreSQL cluster was stopped after verification against its exact
`SHOW data_directory`; data and all recovery artifacts were retained. The existing
Windows PostgreSQL service was unchanged. `owned-cluster-shutdown.json` records it.

`working-source-manifest.json`, `working-tree.patch` and
`review-files-since-entry.zip` preserve the current reviewable files, including
explicitly identified inherited work. `evidence-index.json` binds raw evidence
bytes. These archives are not an accepted release candidate.
