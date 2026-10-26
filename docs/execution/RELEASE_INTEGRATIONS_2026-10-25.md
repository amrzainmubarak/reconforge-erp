# Product integration closure evidence — 2026-10-25

Release decision remains **RELEASE BLOCKED** pending the principal lead's exact-source gates and the mandatory completion matrix. This report qualifies only the corrections and commands below; it does not close whole enterprise domains.

## Verified defects and corrections

| Defect | Root cause and implemented correction | Evidence boundary |
| --- | --- | --- |
| P1 fake HCM, CRM and project results | Three production components initialized hardcoded operational records and locally changed approvals, balances, contracts and invoice totals. Replaced them with real scoped authenticated API commands/reads. Removed invented approver identities, invoice references, assumed two-decimal money calculations and local financial KPIs. | 48 focused component tests independently rerun by Agent A; actual native browser workflows below. |
| P1 asynchronous session/scope leakage | A superseded error body could call session recovery after a successor request. Passive effects alone left a render/response window during scope changes. Request sequence, AbortController, current session revision and synchronous context identity now guard results/errors/recovery. Rendered data is tagged with the exact tenant-session revision, workspace/organization/entity and locale. | Independent A/B review; deferred error-body, workspace-response and logout regressions. |
| P1 classic intercompany artifact object binding | `get_elimination_run(workspace,id)` ignored workspace and `get(id)` selected tenant+id only. Added selected-workspace guards and SQL predicates for persisted/listed/read artifacts; caller scope is never reset. Tenant-only trusted CLI compatibility is retained. | Real restricted-role positive own-source and denied sibling-source reads/list/writes; authenticated API own200/sibling404. Original0063 table RLS is tenant-only; this evidence is for repository/API workspace enforcement, not raw SQL workspace enforcement. |
| P1 unreadable intercompany proposals | API saved an incomplete request envelope without original source lines; deterministic GET replay could not reconstruct it. Native proposal route now uses the existing verified `persist(lines,result,workspace)` contract. | Actual authenticated propose→GET returns both original source lines under selected scope. |
| P1 invoice retry conflict | Omitted `issued_at` generated a new timestamp on retry, conflicting with persisted invoice identity. Native prepare now generates once and reuses the original timestamp inside its locked transaction. Explicit supplied values retain exact identity checks; the UI supplies a stable explicit UTC timestamp. | Native authenticated API retry yields byte-equivalent binding and one source binding; a test time provider refuses any second source timestamp generation. |
| P1 mutable display names used as stable actor IDs | Native artifact `prepared_by` references `identity_users.id`, but the API supplied `username`. CRM creator/reviewer fields also used usernames, allowing identity drift after a rename. Native artifact preparation and audit now use canonical authenticated IDs with a separate display label. CRM stores stable creator/reviewer IDs and requires an immutable creation authority bound under `canonical-user-v1`. Historical rows without that authority refuse409; neither current usernames nor coincident ID strings establish historical authorship. Creation is insert-only, including collision and legacy takeover attempts. The display `approved_by` response is retained and an additive `approved_by_user_id` supplies the stable ID. | Real native users with distinct IDs/names, original invalid-FK caller shape refusal with no artifact retained, renamed creator self-approval400/unchanged Draft, independent canonical reviewer approval, and native proposal replay. |
| P2 unlabelled CRM proration money | API returned minor-unit amounts without currency. Added the saved plans' common currency to the response; UI displays returned exact minor units and currency without assuming precision. | Targeted API/component tests; underlying cross-currency refusal is unchanged. |
| Scanner B101 assistant audit boundary | Runtime assertion was used for a necessary audit connection. Replaced it with explicit503 failure before publishing the response if auditing is unavailable. | Independent Agent B review; scanner and principal-lead final gates remain separate. |

## Reproduced backend failures

Initial affected cohort: **7 failed, 9 passed, 28 errors**, retained in `output/release-blocker-20261025/agent-c-api-before-corrected.log`.

- Six assistant tests passed a MagicMock request with no real backend and supplied financial records/confidence that the repaired server correctly refuses. Replaced these fixtures with migrated SQLite, real authentication, persisted Finance Core sources, explicit foreign-source/injection/autonomous-action refusals and a persisted Draft/no-financial-effect oracle.
- CRM fail-closed test called a generator context manager without entering it or supplying its explicit permission contract. It now enters the context and proves the same503 before any repository is yielded.
- Twenty-eight existing canonical-reference/balanced-line/audit boundary cases patched the removed `set_local_tenant_scope` seam. They now patch the replacement `ensure_repository_tenant_scope` seam solely in their recording adapter; all financial assertions are retained. Native isolation tests separately exercise the real guard.
- Broader treasury recording fixture lacked a current-scope result required by the replacement guard. It now reports its exact tenant/workspace/organization/entity and additionally asserts no scope-reset SQL was emitted.

Successor broader product cohort: **61 passed, 0 skipped**, 136.96s under local Python3.14.6; receipt `agent-c-product-final.json`. This diagnostic is not the required locked3.11/3.12 full program.

## Native and browser acceptance performed

- Locked Python3.12, actual PostgreSQL16.15, official Alembic clean chain through0154, restricted application/personnel roles: `tests/test_release_product_scope.py` **2 passed, 0 skipped**,21.13s; receipt `agent-c-native-product-final.json` binds unchanged broad source fingerprint before/after. Agent A independently reran the sibling-artifact case **1 passed, 0 skipped**,17.98s.
- The earlier distinct-identity/renamed-creator proof passes **2 tests, 0 skipped**,28.65s in `agent-c-distinct-identity-final.log`; independent review subsequently rejected the historical-username compatibility inference because usernames can be reused and can overlap the ID namespace. Those passes do not qualify that rejected helper. The successor uses migration-backed immutable creation authority; its latest native/SQLite proof is pending. An earlier command labelled `before` overlapped source edits and passed; it is retained as an intermediate observation, not evidence that the earlier source reproduced or passed the new contract. Final exact-source qualification remains the principal lead's gate.
- Dedicated actual HTTPS native browser harness: **2 passed, 0 skipped**,35.1s; receipt `agent-c-native-browser-headless149.json`, source fingerprint unchanged throughout the run. Runtime: locked Python3.12 and explicit installed Google Chrome for Testing149.0.7827.55/headless1228. Standard package-pinned Chrome151/1234 initially absent; matching download is separately tracked. No supported-current-browser gate is inferred from the installed149 run.
- Actual browser path: maker submits leave; self approval400; checker approves and persisted available balance becomes18. CRM checker approves a persisted original quote, suspends and resumes a persisted contract. Project checker verifies original deliverable; maker prepares and safely retries the canonical draft; same-maker review is refused; checker reviews; poster posts and reads the posted binding. Session cookie is HttpOnly/Secure/SameSite Strict.
- Actual Arabic390px path: foreign-workspace request403, no confirmed source result; all three views RTL, no horizontal document overflow, zero axe violations for the focused WCAG2A/AA/2.1AA/2.2AA checks; logout disables financial posting. This is bounded automated evidence, not full WCAG conformance or human UX research.

No HTTP response or operational record is mocked in the native browser runtime. Its harness imports the production components unchanged and uses real password-authenticated identities and migrated native repositories. Synthetic fixtures are provisioned only in unique disposable PostgreSQL databases. The failed setup/browser-launch attempts are retained separately.

## Reproduction

From repository root, with the mandatory native environment provisioned:

```powershell
python -m pytest tests/test_release_product_scope.py
npm --prefix apps/web run typecheck
npm --prefix apps/web run test:run -- src/components/HcmLeaveWorkspace.test.tsx src/components/CrmSubscriptionWorkspace.test.tsx src/components/ProjectMilestoneWorkspace.test.tsx
```

Build the dedicated browser artifact from `F:\reconforge-erp\apps\web`:

```powershell
node node_modules/vite/bin/vite.js build --config e2e/release-product.vite.config.ts
```

Then from repository root:

```powershell
node apps/web/node_modules/@playwright/test/cli.js test --config apps/web/e2e/release-product.playwright.config.ts
```

The browser config defaults to the package-pinned browser with no skips/retries. `RECONFORGE_RELEASE_PRODUCT_PYTHON` selects the locked interpreter. `RECONFORGE_RELEASE_BROWSER_EXECUTABLE` permits an explicitly recorded installed-browser diagnostic. CI must use its ordinary matching browser installation and real PostgreSQL environment; no existing mandatory gate is excluded.

## Mandatory integration work still unqualified

The existing `ENTERPRISE_COMPLETION_MASTER_MATRIX.md` remains authoritative. This bounded repair does not close its INCOMPLETE domains. Concrete remaining requirements include:

- CRM contract termination currently refuses403 until a persisted independent approval exists; there is no completed termination approval/fee posting journey. Subscription cancellation calculates a refund but does not establish a governed native cash refund. These must not be presented as complete financial workflows.
- Manufacturing quality records explicitly return `inventory_effect: not_posted`/`financial_effect: not_posted`. Their existence does not prove stock holds, scrap valuation, rework labor/parts or GL effects. The matrix's combined demand→supply→quality→finished-goods closure remains unqualified.
- Leave deductions are calculations; the repaired leave UI is not evidence of complete leave-to-payroll, statutory payroll or country coverage integration.
- Full group reporting/FX close, all inventory/return combinations, populated whole-schema restore, current source-frozen hosted CI, and all other required acceptance remain separate principal-lead gates.

No mandatory item was reclassified optional, and no full-domain completion or external security/certification claim is made.
