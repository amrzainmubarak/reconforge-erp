# Enterprise integration and primary Studio transformation — 2026-10-26

**RELEASE BLOCKED. No full-program acceptance, merge or production deployment.**

Implementation source: `f3cfbad9` on `amr/assurance-prerequisite-repair-20261025`.
Entry HEAD was `d487fc83`; remote Draft PR143 entered at `ff8a45cb` with seven
failed jobs. The inherited repairs were preserved before integration. Final
hosted qualification must refer to the pushed source, not those historical jobs.

## Implemented repairs

| Root cause | Correction | Evidence and boundary |
|---|---|---|
| Mutable HCM usernames could transfer ownership or permit self-review | Canonical stable requester/reviewer IDs; display labels remain separate | Original four failures retained; unchanged local regression and independent native authorization tests pass |
| Leave RLS protected tenant/workspace but disclosed sibling legal entities | Revision0156 binds both tables through the canonical employee organization/entity, with USING and WITH CHECK | Independent native15 cohort includes direct SELECT/UPDATE/INSERT denial, legitimate unbound HR provisioning, empty policy roundtrip and populated downgrade refusal |
| Invalid persisted capacity restrictions silently became empty sets; compact dates bypassed exact blackout membership | Reject malformed shapes/types and noncanonical dates before scheduling; domain/API also reject invalid dates before persistence | Original27 malformed-data failures and compact-date bypass retained; native3 corruption cases preserve reservation state; independent domain/API73 cases pass |
| SQLite quality construction committed unrelated caller work | Savepoints and individually owned schema statements | Independent transaction3 cases; no stock quarantine or GL claim |
| Multi-register acquisition falsely used the exact single-register source schema | Refuse before transaction/I/O pending a versioned native owner | Native state equality over18 tables plus supported single-register acquisition/depreciation/disposal; multi-register functionality remains BLOCKED |
| Stale HCM/CRM/project results could outlive edited inputs | Shared request generation, abort and input invalidation | Focused54 UI cases; real authenticated HCM/CRM/project browser2 journeys |
| CRM source provenance, scope and migration defects in inherited work | Preserve reviewed canonical author storage, workspace line keys and atomic migration rollback; retain existing Finance Core bridge | Native migration/bridge25 cohort, including restore/replay and no inferred legacy author |
| Historical receipts compared old policy subjects to refreshed dependencies | Bind immutable reports to retained policy bytes without rewriting reports or weakening hashes | Historical binding/CI contract tests; no acceptance of current dependencies from old evidence |
| Direct parser inventory omitted persisted JSON and hardened invoice XML | Exact AST accounting with PARTIAL coverage and explicit residual limitations | Independent source review and parser/XML tests; no blanket secure-ingress claim |

Backend integration checkpoint: **215 passed, zero skipped**, unchanged source
digest `f19f4285b90ed72e6b16da05e0179a627fd27b24729d41a14ae74b1ec79f79c6`.
Full Ruff, mypy (898 files), Bandit and package build pass at that checkpoint.
Subsequent commit hygiene removes one trailing blank line in a Python contract
and one in the central TypeScript route file; route tests13 and typecheck pass.
The strict current CI/history cohort passes137 with an unchanged successor digest.
The final combined native cohort passes51 with zero skip/xfail/xpass in824.297s
process time, and the full frontend1257 cases pass in103.891s on implementation
commit f3cfbad9. Both retain unchanged source digest
`0729d8ce0a50be55b7afa574efec9ee43f5a9b35f7bba92bc139b185a7ee4eee`.
The primary main-App browser passes2/2 on that same source/digest (130.594s).
Every raw receipt preserves its own before/after source digest; do not reassign
predecessor receipts to a later commit or call them whole-source release acceptance.

## Actual connected business evidence

The new native API journey uses persisted maker/checker/poster identities and a
single synthetic ten-unit receipt. Four units ship through reservation and FIFO,
then invoice, AR and cash collection. Independent SQL derives inventory7,200,
COGS4,800, revenue/cash18,000 minor USD, AR0, balanced GL and four posting effects.
Exact lost-response retry does not duplicate cash. This is a **partial cycle1**;
no CRM lead/quotation origin or full reporting chain is inferred.

All five required full cycles remain **BLOCKED**, with exact stage gaps in
[the independent cycle matrix](ENTERPRISE_CYCLES_2026-10-26.md). Legacy integration
helpers are independently verified to create balanced **Draft** entries and zero
posting effects; they are not counted as financial publication.

## Primary application UI

The real React App preserves53 navigation destinations in eight searchable,
collapsible sections. Sidebar, mobile shortcuts and palette share capability
checks from authenticated `/auth/me`; denied deep links cannot mount gated content.
The shell provides breadcrumbs, RTL/LTR, light/dark themes, focus-managed mobile
navigation, persistent collapse, actual session identity and confirmed logout.
Shared operational controls and named table overflow containers apply directly to
the existing product. [Complete route inventory](STUDIO_NAVIGATION_2026-10-26.md).

- Frontend: **1,257 tests / 115 files passed**, typecheck and production build pass.
- Main-App native browser: **2 passed**, explicit Python3.12.13 and real PostgreSQL.
- Twenty width/language/theme observations:360/390/768/1024/1440, Arabic/English,
  light/dark; zero observed document overflow and zero Axe findings in the tested
  shell/financial-page scope. Twenty-nine genuine PNGs have dimensions and SHA256.
- Existing real HCM/CRM/project browser journeys: **2 passed**, zero retry.
- No human completion-time savings or user satisfaction was measured. No whole-app
  WCAG conformance or manual screen-reader qualification is asserted.
- The authorized workspace list is informational. **Global cross-page workspace
  switching and live role-specific dashboards are not implemented.**

Before: `output/assurance-20261026/studio-before-desktop.png` and mobile counterpart.
Final exact-source after: `output/enterprise-program-20261026/studio-f3cfbad9/`
(and retained earlier `studio-shell-final-312/`) with measurements,
raw Axe reports and screenshot manifest. Python3.14 exploratory captures are
separately retained and excluded from final browser acceptance.

## Quality and remaining gates

Broad entry diagnostic: **10,208 passed /25 failed /538 setup errors /916 skipped**
of11,687 cases,2033.578s process. Every setup error lacked the PostgreSQL admin DSN.
The run changed source concurrently and is not a final frozen regression. Original
failures, environment errors and later fixes remain separate artifacts. Targeted
successors resolve the reproduced HCM, parser, policy, scope and fixture defects.

One current test remains deliberately red:
`tests/test_manufacturing_quality_rework.py::test_quality_api_routes` expects actual
quarantine, while the server accurately returns `recorded` and `inventory_effect:
not_posted`. The missing quality-to-inventory integration is retained as a blocker;
the test is neither disabled nor weakened. Unsupported multi-register operations
and all full-cycle gaps are also open.

| Gate | Decision |
|---|---|
| A critical defects | Bounded repairs verified; unresolved quality/inventory contract and complete release security qualification remain open |
| B five connected cycles | BLOCKED:0/5 complete; partial native stock-to-cash only |
| C navigation | Implemented with53 preserved destinations and bounded permission/browser proof; hosted final-source qualification pending |
| D UI/UX | Shell and shared foundations verified; global switching, role dashboards and whole-product accessibility remain incomplete |
| E independent QA | Bounded native/security/financial/transaction and navigation reviews pass; not a universal audit |
| F GitHub qualification | Pending final pushed-source CI, complete image/install/provenance/restore gates; no release acceptance |


## Exact image and artifact boundary

The Docker image built on implementationf3cfbad9 passes `reconforge doctor`.
Config digest: `sha256:bb63260400c8c4c2597f4c31bec5cd84ff57c96338ed108dbece7f938e58ed3a`.
An independent byte comparison of1,054 Python/Alembic files (CRLF→LF only)
matches the Git source in both the installed image and the wheel. Wheel install
and doctor pass against the reviewed Python3.12 dependency environment; this is
not a clean-environment or air-gap installation qualification. The sdist/wheel
build receipt records temporary documentation-only drift; code closure is verified
separately. Whole-archive release provenance/signatures are not qualified.

Fresh Syft/Grype evidence passes the existing fail-closed container policy:
**0 Critical /0 High /9 Medium /1 Negligible**, with zero active exceptions.
The medium matches are CPython and BusyBox packages, not zero vulnerabilities.
The supported upstream Python3.12.16 security release was identified, but the
selected official `python:3.12.16-alpine3.24` tag returned `not found`; no image
digest or alternative runtime was invented. Residual applicability and distribution
remediation remain open. Primary-source triage and raw scanner output are retained
under output/enterprise-program-20261026 and
[the primary-source triage](IMAGE_RESIDUAL_TRIAGE_2026-10-26.md).
[Tracked image policy evidence](IMAGE_SECURITY_2026-10-26.json) retains all counts.

Windows browser logs retain Proactor ConnectionResetError10054 during disconnect
teardown despite passing journeys; no clean-server-log assertion is made.
After every native/browser process completed, root verified the owned PostgreSQL
data_directory and zero other clients, stopped only that cluster, and preserved
all data/evidence. The existing Windows PostgreSQL service was not modified.

## Publication correction after the runtime freeze

The actual f3cfbad9 sdist omitted its new HTML/TSX browser harness and MJS capture
manifest. The archive gate also expected149 revisions/head0150 instead of the
current155/head0156. Three red contract tests and the original archive hashes are
retained. The export now admits only required source extensions, and the existing
safe archive inspector requires the closed Studio support set and current chain.
Twenty focused tests and independent QA pass. No financial or UI runtime logic
changed. Actual rebuilt-archive inspection is recorded separately under
output/enterprise-program-20261026/publication-source-inspection*.json; no pass is
inferred from the unit results. See ADR0874. The frozen runtime remains f3cfbad9;
its source, browser, image and native evidence is not relabelled as a later run.

## Recovery, ownership and reproduction

Only `F:/reconforge-erp` was used. No worktree, main mutation, force push or merge.
Principal lead owns Git/shared registries; engineering, independent QA and product
agents used exclusive files. All business fixtures are synthetic.

Entry recovery: `output/enterprise-program-20261026/entry-recovery.zip`,
`entry-manifest.json`, `entry.patch`; earlier assurance bundles remain unchanged.
Raw command receipts and failures are under `output/assurance-20261026/program-*`,
engineering-program/capacity receipts and qa-program receipts. Each records commands,
times, exit codes, source digests, log hashes or per-file ownership fingerprints.
JUnit and the broad failure classification are under `output/enterprise-program-20261026`.

Rollback: revert the isolated Studio commit for UI, retaining route contracts.
Do not downgrade156 over populated leave data; use forward recovery or a separately
verified isolated restore. No destructive cleanup of prior unsupported drafts was
performed. The SQLite/PG migration and financial source restrictions remain intact.

## Published checkpoint and hosted negative

Draft PR143 publishedD5 (`d5c6a1a6ec2726a3755161300f44965aaf47d725`).
Fresh source archive inspection passed20.625s with all155 revisions/head0156:
`output/enterprise-program-20261026/publication-source-inspection-d5c6a1a6.json`
SHA256 `097452d79fd8fdcfb302fc11148873bfc0dc43d7890e3abf1bf91ff46ca37d3b`.
Hosted Docker40377041829 and CodeQL40377041696 passed. Security40377476239
passed exact-image and locked Python3.11/3.12 gates but failed secret history
scan and aggregate. The sole redacted finding is historical4ce241 line80 of
ASSURANCE_2026-10-25.json, a source-file SHA256 under web_files_sha256. Independent
review reproduces it from the historical source with Windows CRLF expansion;
raw Git LF bytes have a different hash. Exact reviewed handling is separate,
with original failure retained. Full CI40377041698 remains pending; no hosted
release acceptance is claimed.

## Hosted-failure corrections, successor runtime2bfbdcd2

Hosted standard browser E2E exposed four failures: active Foundation badge
contrast, two signed-in test fixture/navigation contracts, and a collapsed
Inventory destination. Original4-failure/13-pass run is retained. The actual
active badge now uses opaque semantic colors (measured11.16:1); notification
fixture supplies authoritative auth/me permission, exact local sign-in avoids
an ambiguous global action, and screenshot navigation uses actual sidebar
search. All assertions remain. Focused actual browser17/17 and typecheck pass;
full frontend1257/115 files pass again (113.719s process,103.45s Vitest). Whole
source receipt changed only because independently owned security metadata was
being finalized; this is frontend-scoped evidence, not a frozen whole-source run.
No Python/Alembic runtime changes occurred afterf3cfbad9; its native evidence is
retained as ancestor/component proof, never relabelled as a successor run.

ADR0875 and commitc2020a80 admit only paired exact historical/current scanner
fingerprints for the same public source hash. Full immutable report bytes (LF
orCRLF), exact line and JSON member/value are enforced before allowance. Neither
the original report nor scanner rules were changed. Independently reviewed
policy83 and combined publication/policy86 pass. Checksum-verified official
Gitleaks8.30.1 current-tree scan passes zero findings. Local --all additionally
finds an unrelated nonancestor historical fixture on another local branch;
that finding remains unsuppressed and is not a PR qualification result. Hosted
original failure and local current-tree red/successor green are retained under
output/enterprise-program-20261026/gitleaks and hosted-secret-scan.

Latest runtime is2bfbdcd2. Source-frozen release acceptance remains **BLOCKED**;
new hosted results must name the successor head explicitly. Earlier D5 Docker,
CodeQL and dependency/image passes do not automatically qualify this successor.
