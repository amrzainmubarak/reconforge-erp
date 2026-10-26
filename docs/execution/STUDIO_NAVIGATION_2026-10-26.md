# Studio navigation and interface foundations — 2026-10-26

## Scope and design decision

ReconForge remains a local-first financial integrity and operations control platform alongside source systems. This change reorganizes the existing Studio application; it adds no financial posting authority or ERP product claims. The supplied execution brief substitutes for a design interview in this delegated task.

Mode: Operate. Finance operators work in sustained sessions on desktop screens and review on mobile. The design retains the existing restrained teal identity, offers light/dark/system preferences, and uses a neutral content surface, compact section navigation and one consistent financial form/table vocabulary. Existing route behavior and source provenance stay intact.

## Reproducible baseline

Before edits the actual App rendered 53 destinations in five groups, including 27 in its first group. Genuine signed-out source captures from Vite at `/enterprise-finance`: `output/assurance-20261026/studio-before-desktop.png` (1440×1024) and `studio-before-mobile.png` (390×844). These are browser captures of actual source, not authenticated evidence. No task-time or usability-time saving was measured.

## Route-to-navigation inventory

Every previous destination appears once below. Aliases `/erp`, `/crm-contracts`, and `/project-milestone-billing` retain their original canonical route mapping. Route parsing and URL generation now live together in `apps/web/src/studio-routes.ts`.

| Section | Destination | Route / target | Navigation capability predicate |
|---|---|---|---|
| Workspace | Dashboard | `/` | Existing preview / local destination; operation-specific authorization remains at server |
| Workspace | Exceptions | `/exceptions` | ANY: exceptions.read, exceptions.manage |
| Workspace | Evidence binder | `/evidence` | Existing preview / local destination; operation-specific authorization remains at server |
| Workspace | Notifications | `/notifications` | ANY: notifications.read |
| Finance & close | Finance & reporting | `/enterprise-finance` | ANY: finance_core.read, finance_core.manage, finance_core.validate |
| Finance & close | Financial statements | `/financial-reporting` | ANY: finance_core.read |
| Finance & close | Receivables | `/receivables` | ANY: receivables.read, receivables.manage, receivables.approve, receivables.credit_override |
| Finance & close | Budget control | `/budget-control` | ANY: budget_control.read |
| Finance & close | Fixed assets | `/fixed-assets` | ANY: finance_core.read |
| Finance & close | Accruals and prepaid expense schedules | `/accrual-deferral` | ALL: accrual_deferral.read, finance_core.read |
| Finance & close | Currency & tax | `/operational-fx-tax` | ANY: finance_core.read |
| Sales & customers | Sales & revenue | `/sales-revenue` | ALL: sales.read, receivables.read, finance_core.read |
| Sales & customers | Product sales | `/stock-sales` | ALL: sales.read, inventory.read, receivables.read, finance_core.read |
| Sales & customers | Customer returns | `/customer-returns` | ALL: sales.read, receivables.read, inventory.read, finance_core.read |
| Sales & customers | CRM contracts & prorated subscriptions | `/crm-subscriptions` | ANY: sales.manage, sales.approve |
| Sales & customers | Professional invoice / payment | `/professional-invoice-payment` | Existing preview / local destination; operation-specific authorization remains at server |
| Purchasing & inventory | Procurement & payments | `/procurement-operations` | ALL: finance_core.read, inventory.read, payables.read |
| Purchasing & inventory | Partial procurement | `/procurement-partial` | ALL: finance_core.read, inventory.read, payables.read |
| Purchasing & inventory | Procurement sourcing | `/procurement-sourcing` | ALL: budget_control.read, finance_core.read, inventory.read, payables.read, procurement_sourcing.read |
| Purchasing & inventory | Inventory controls | `/inventory` | Existing preview / local destination; operation-specific authorization remains at server |
| Purchasing & inventory | Inventory receipts | `/inventory-receipts` | ALL: finance_core.read, inventory.read |
| Purchasing & inventory | Warehouse transfer | `/inventory-transfer` | ALL: finance_core.read, inventory.read, inventory.valuation.read, inventory_transfer.read |
| Manufacturing | Manufacturing execution | `/manufacturing-execution` | ALL: finance_core.read, inventory.read, manufacturing_execution.read |
| Manufacturing | Manufacturing execution v2 | `/manufacturing-execution-v2` | ALL: finance_core.read, inventory.read, manufacturing_execution.read, manufacturing_execution_v2.read |
| Manufacturing | Manufacturing supply and planned procurement | `/manufacturing-supply-plan` | ALL: budget_control.read, finance_core.read, inventory.read, manufacturing_execution.read, manufacturing_execution_v2.read, manufacturing_supply_plan.read |
| Manufacturing | Master production schedule & ATP | `/master-production-schedule` | ANY: manufacturing_supply_plan.read, manufacturing_supply_plan.manage |
| Manufacturing | Shop floor dispatch & lot genealogy | `/shop-floor-traceability` | ANY: manufacturing_execution.read, manufacturing_execution.manage |
| Manufacturing | Manufacturing cost control | `/manufacturing-cost` | Existing preview / local destination; operation-specific authorization remains at server |
| People & projects | People, projects and wage accounting | `/people-project-payroll` | ANY: people_project_payroll.read, people_project_payroll.personnel, people_project_payroll.manage, people_project_payroll.read_sensitive |
| People & projects | Employee leave & absence governance | `/hcm-leave` | ANY: people_project_payroll.personnel, people_project_payroll.manage, people_project_payroll.approve_time |
| People & projects | Project source cost and revenue reconciliation | `/project-source-reconciliation` | ALL: people_project_payroll.read, project_time_billing.read, finance_core.read, receivables.read |
| People & projects | Project billing and collections | `/project-time-billing` | ALL: project_time_billing.read |
| People & projects | Project WBS & milestone billing | `/project-milestones` | ANY: project_time_billing.read, project_time_billing.manage |
| Group & settlements | Intercompany operations | `/intercompany-operations` | ALL: intercompany_operations.read, finance_core.read |
| Group & settlements | Intercompany foreign trade | `/intercompany-fx` | ALL: intercompany_fx.read, finance_core.read |
| Group & settlements | Selected-source group reporting diagnostic | `/intercompany-group-diagnostic` | ALL: intercompany_fx.read, finance_core.read |
| Group & settlements | Paired-trade source cashflow | `/intercompany-source-cashflow` | ALL: intercompany_fx.read, finance_core.read |
| Group & settlements | Consolidated group financial statements | `/consolidated-statements` | ANY: finance_core.read, finance_core.manage |
| Group & settlements | Bank reconciliation | `/bank-statement` | Existing preview / local destination; operation-specific authorization remains at server |
| Group & settlements | Retail settlement | `/retail-settlement` | Existing preview / local destination; operation-specific authorization remains at server |
| Group & settlements | Individual cashflow | `/individual-cashflow` | Existing preview / local destination; operation-specific authorization remains at server |
| Platform & administration | Reconciliation | `local Studio/reconciliation` | Existing preview / local destination; operation-specific authorization remains at server |
| Platform & administration | Month-end close | `local Studio/close` | Existing preview / local destination; operation-specific authorization remains at server |
| Platform & administration | Governed AI Assistant | `/governed-assistant` | ANY: ai.query, finance_core.read |
| Platform & administration | Reports | `local Studio/downloads` | Existing preview / local destination; operation-specific authorization remains at server |
| Platform & administration | Control packs | `local Studio/control-packs` | Existing preview / local destination; operation-specific authorization remains at server |
| Platform & administration | Mapping Studio | `/mapping` | Existing preview / local destination; operation-specific authorization remains at server |
| Platform & administration | Rule Studio | `/rules` | Existing preview / local destination; operation-specific authorization remains at server |
| Platform & administration | Live Studio | `/live` | ANY: metrics.read |
| Platform & administration | Administration audit | `/admin-audit` | Identity entry stays reachable; server authorizes each admin action |
| Platform & administration | Durable jobs | `/jobs` | ANY: ops.read |
| Platform & administration | Settings | `Planned; disabled` | Unavailable |
| Platform & administration | Developer console | `local Studio/docs` | Existing preview / local destination; operation-specific authorization remains at server |

The `StudioPage` type also contains `treasuryLiquidity`, `manufacturingBom` and `intercompanyEliminations`; the incumbent App has no rendered route/navigation destination for these values. This redesign does not invent new screens for them.

## Behavior and limits

- Eight task-based sections preserve all 53 destinations. The current section opens on direct URLs; section disclosures support keyboard and pointer collapse, with one expanded section at a time. Search opens every matching section, includes translated labels and stable route keywords, and provides a localized empty state. The icon rail retains accessible names and titles. Desktop collapse persists only a boolean layout preference.
- The sidebar, mobile shortcuts and command palette consume the same navigation groups and permission predicate. Authenticated capabilities come from fresh same-origin `/api/v1/auth/me`, never from client role names. Pending/invalid/error responses hide gated destinations and prevent mounting gated deep-link content. Generation and abort guards discard prior-session responses. Explicit retry is available. Backend permissions and hierarchy remain authoritative on every operation.
- The global session strip shows the actual authenticated username and tenant, lists server-returned authorized workspace IDs, and offers confirmed server logout. The list is informational: **cross-page workspace switching is not implemented**. Existing forms select their own authorized workspace/organization/entity scope.
- Mobile navigation is a modal drawer with inert closed state, focus containment, Escape close, focus restoration and body scroll lock. The shared command palette accepts arrow keys, Tab and Escape. RTL uses logical layout properties; full navigation names remain accessible when labels truncate.
- Group-aware breadcrumbs replace hard-coded finance categorization. Shared operational CSS defines form controls, focus states, theme colors, typography and tables. `StudioPageHeader` and `StudioTableViewport` are used by the actual enterprise finance page; tables have named keyboard-reachable overflow viewports.
- The existing synthetic dashboard and artifact views remain explicitly preview surfaces. Authenticated evidence uses the actual native financial page and posted trial-balance API; no dashboard values were invented.

## Validation and evidence

Focused tests cover destination/route preservation, exact permission combinations, denied-role-name inference, invalid responses, retry and stale session rejection. Existing App, recovery and navigation tests are retained. Native acceptance uses `tests/test_studio_shell_browser_runtime.py`, a disposable PostgreSQL fixture with canonical authenticated identities, maker/checker/poster posting, and an additional restricted real user. No API mocking is used in that browser suite.

Run from the repository root:

```powershell
npm --prefix apps/web run typecheck
npm --prefix apps/web run test:run -- src/navigation-access.test.tsx src/components/Navigation.test.tsx src/App.test.tsx src/App.workspace-recovery.test.tsx src/components/EnterpriseFinanceWorkspace.test.tsx
npm --prefix apps/web run build
```

Run the dedicated native browser gate from `apps/web` with the existing PostgreSQL test environment configured:

```powershell
npm exec -- vite build --config e2e/studio-shell.vite.config.ts
npm exec -- playwright test --config=e2e/studio-shell.playwright.config.ts
node e2e/studio-shell.manifest.mjs
```

The suite targets the real main App, real login, step-up, real posted table, native denied navigation and confirmed logout. It writes timestamped measurements and raw axe reports for widths 360/390/768/1024/1440 in Arabic/English and light/dark themes under `output/assurance-20261026/studio-shell/`. Browser traces and local synthetic credentials remain local test artifacts. Results must be read from the retained logs; this document alone does not assert a pass.

## Rollback and acceptance boundaries

Source-only change; no data/schema migration. Restore the prior App/navigation/topbar/overlay/styles files and remove the new route/access/foundation components to revert the shell. Keep the original destinations, permissions and financial workflow source files. A UI visibility predicate is not authorization, scope switching, regulatory compliance or proof of financial completeness. Native browser evidence and independent QA review are required before treating the shell slice as accepted.

## Final bounded receipt

- Full frontend suite: **115 files / 1,257 tests passed**, 120.52 seconds, `npm --prefix apps/web run test:run -- --maxWorkers=2`; log `output/assurance-20261026/studio-full-tests.log`.
- Final TypeScript check: exit 0; `studio-typecheck-final.log`. Production `npm run build`: exit 0; `studio-build.log`. Mechanical design detector: `[]`; `studio-design-detector.json`.
- Independent QA: 13 navigation/route tests passed; `qa-program-navigation-final.log`; no remaining actionable finding in the bounded route/permission/focus review.
- Final real main-App browser run: **2 tests passed**, Python **3.12.13** via the retained supported virtual environment; `studio-native-browser-final-312.log` and `studio-final-python-version.log`.
- Final evidence is separately retained in `output/assurance-20261026/studio-shell-final-312/`: 20 measured viewport/locale/theme combinations, zero recorded document overflows, zero axe violations across the shell **and actual financial page**, plus four authenticated drawer captures and five long-identity captures. `screenshot-manifest.json` records raw PNG dimensions, byte counts, SHA-256 and filesystem timestamps for all **29** genuine captures. `measurements.json` records capture timestamps and viewport dimensions. The actual financial table shows 30.01 USD debit and credit from a native maker/checker/poster posted 3,001-minor-unit source.
- Manual final visual inspection covered the actual English desktop financial table and Arabic dark mobile drawer. The active finance group and current route are visible after rail-to-desktop transitions; footer and scope controls remain reachable.
- Earlier unsupported Python 3.14 exploratory evidence is retained separately as `studio-shell-exploratory-314-final/` and `studio-native-browser-exploratory-314.log`. The initial report request refusal before step-up is retained in `studio-native-browser-first.log`; acceptance adds actual human reauthentication rather than weakening authorization. Windows TLS disconnect callbacks remain in raw logs; browser assertions passed on the supported runtime.

To reproduce the local supported final receipt, set `RECONFORGE_RELEASE_PRODUCT_PYTHON` to the Python 3.12 executable and `RECONFORGE_STUDIO_SHELL_OUT` to an absolute evidence directory before build, browser tests and manifest generation. CI can use its configured supported Python and the default output directory. CI browser-gate wiring is maintained by the lead; this delegated slice does not claim the full release gates are accepted.
