# Independent enterprise cycle qualification — 2026-10-26

Release decision: **BLOCKED**. None of the five complete mandatory cycles is
qualified by this review. Component tests and operational screens do not prove
connected end-to-end source ownership, financial posting or reporting.

This review uses synthetic fixtures only, the existing restricted PostgreSQL
runtime, and the official Alembic chain. It does not change production data,
the Windows PostgreSQL service, CI selection or inherited browser harnesses.

## Required cycles and evidence gaps

| Cycle | Actual interfaces and existing component evidence | Missing qualification on one coherent source chain | Status |
|---|---|---|---|
| 1: Lead → Opportunity → Quotation → Approval → Sales Order → Inventory Reservation → Fulfillment → Invoice → AR → Collection → GL → Reporting | `crm_contracts.py` exposes opportunities, quotations, approval and contract conversion. `stock_sales.py` exposes governed stock orders, reservation, FIFO issue, invoice and cash phases. Existing native stock-sales API tests exercise these later owners. New independent four-unit API journey checks actual remaining inventory and canonical GL. | No evidence here that a lead produces an opportunity whose approved quotation is the authoritative origin of the stock order; the new order is deliberately identified as directly supplied synthetic input. No final full-cycle reporting/browser qualification. | BLOCKED |
| 2: Material Requirement → MRP → Purchase Requisition → Supplier Quotation → PO → Goods Receipt → Inventory/FIFO → Production Order → Material Issue → WIP → Manufacturing Execution → Quality → Finished Goods → GL | `manufacturing_supply_plan.py` has plans, requirements, requisition, quote, award and receipt preparation routes. Native manufacturing-execution-v2 tests cover original expense-backed material, WIP, quality hold, saleable finished goods and abnormal loss. | Those independently seeded fixture chains have not been joined into one original requirement/PO/receipt/FIFO/production genealogy with a single independent quantity/cost/GL oracle in this program. | BLOCKED |
| 3: Employee → Employment Contract → Attendance → Leave → Payroll Preparation → Independent Approval → Payment → GL → Employee Reporting | `people_project_payroll.py` exposes employee, employment, approved time and governed payroll operations; `hcm_leave.py` exposes leave. Existing release HCM regressions reproduced four failures at program entry. | Stable employee ownership/reviewer identities and canonical entity RLS now pass the independent native15 cohort. No connected attendance/leave-to-payroll inclusion/exclusion and employee-report oracle is claimed. | BLOCKED |
| 4: Customer Contract → Project → Resources → Timesheets → Costing → Milestone Approval → Invoice → AR → Collection → GL → Profitability | CRM contract routes, project-time-billing routes, original time claims and project-milestone canonical bridge exist. Existing project-time-billing native tests cover whole approved time, AR, partial/final cash and original command replay. | Contract, resources, approved times/costing and milestone owner are not proved as one coherent master/source chain in this program. Operational project summary is not proof of posted profitability. | BLOCKED |
| 5: Company A transaction → Company B counterparty effects → Settlement → FX → Intercompany Elimination → Group Consolidation → Statements | `intercompany_fx.py` and existing native tests cover paired recognition, settlement, revaluation, translation and elimination. Consolidation/statement interfaces also exist. | No single matched two-company source, paired settlement, FX policy, elimination and group-statement reconciliation is independently qualified here. Separate elimination artifacts/bridges do not establish that full chain. | BLOCKED |

## New connected independent regression

`tests/test_enterprise_program_stock_to_cash.py` operates the actual selected-scope
HTTPS API against a disposable database migrated to head, using persisted maker,
checker and poster identities. A ten-unit synthetic receipt costs 12,000 USD
minor units. Four shipped units cost 4,800; six retained units cost 7,200. Four
units sold at 5,000 less 10% produce revenue and cash of 18,000. The oracle reads
native FIFO layers and canonical posted-effect entry lines independently of the
operation response. AR must net to zero and total GL debits minus credits to zero.

It refuses reviewer publication of delivery/invoice/cash, then retries the exact
final cash command after a simulated lost response. Four canonical posting
effects must remain: receipt, issue, invoice, collection. This is a partial
cycle-1 qualification, not evidence for its unimplemented/unconnected origins.

The first run completed the API chain but the independent query incorrectly
filtered an invented `Posted` status spelling and therefore returned zero rows.
That oracle defect is retained in `qa-program-stock.log`; the correction joins
`finance_posting_effects`, the actual canonical publication owner.

`tests/test_enterprise_program_asset_authority.py` independently challenges
Agent A's native multi-register source closure. Its first version required exact
replay and challenged secondary cost, primary impairment account and register
ordering. That native challenge exposed an incompatible source schema. Following
the lead's conservative decision, the acceptance version requires explicit
`asset_multi_register_owner_required` before any change, with byte-identical full
rows across eighteen relevant source, command, GL, audit and outbox tables for
four request shapes. It then completes the supported single-register acquisition,
depreciation and disposal with independent final account balances. Safety closure
does not qualify native multi-register accounting.

## Commands and runtime custody

The retained cluster is the owned directory
`output/blocker-closure-20261025/postgres/data`, bound to loopback port 55449.
It was started with `pg_ctl` after explicit lead coordination. After all native
and browser work, the lead verified the exact directory and zero other clients,
then stopped only this owned cluster with data retained (owned-cluster-shutdown.json). Connection values are loaded privately from the retained
setup file by the evidence runner; do not copy them into documentation.

```powershell
$env:RELEASE_NATIVE='1'
& output/release-blocker-20261025/venv312/Scripts/python.exe `
  output/assurance-20261026/run_evidence.py qa-program-native `
  output/release-blocker-20261025/venv312/Scripts/python.exe -m pytest `
  -p tests.mandatory_native_gate -o addopts= -q --tb=short `
  tests/test_enterprise_program_stock_to_cash.py `
  tests/test_enterprise_program_asset_authority.py `
  --junitxml=output/assurance-20261026/qa-program-native.xml
```

Current results and hashes belong to `output/assurance-20261026/qa-program-*.json`,
logs and XML, not inferred from file existence. Tests remain unqualified until
their real command completes without skip, xfail or xpass. No new browser
qualification is claimed by Agent B. Agent C owns genuine before/after main-App
screenshots; detached component harness evidence remains separately scoped.

The first combined native command collected two cases with zero skipped, xfailed
or xpassed: **one passed, one failed** in 61.47 seconds. The connected stock-to-cash
API/FIFO/GL oracle passed. The multi-register test found that identical acquisition
replay reaches `asset_close` and is refused with `Asset and plan require their
exact versioned schemas`. The adapter marks an extended multi-register object as
`fixed-asset-v1`, while the native owner accepts the exact original v1 key set.
Agent A's cursor-boundary request-digest tests cannot establish this native
closure. This defect remains BLOCKED pending a versioned native contract or an
explicit fail-closed supported-surface decision. Do not bypass `asset_close` or
permit arbitrary extra JSON keys to obtain a green test.

Independent native HCM challenge `qa-program-hcm-native` collected five cases:
four passed and one failed in 48.75 seconds, zero skipped/xfail/xpass. Stable
identity rename and forged-owner self-review checks passed; an HR actor in one
legal entity could read another entity's annual entitlement balance in the same
workspace (HTTP 200 instead of 403/404). The inherited test also checks other
balance/request mutations after this first refusal, so those later assertions
have not passed in this run. Agent A owns the central object admission repair;
cycle 3 remains BLOCKED pending independent rerun. The receipt has matching source
digests before/after this command.

After the conservative multi-register gate, `qa-program-native-closed` passed both
new cases in 76.60 seconds with zero skipped, xfailed or xpassed. This qualifies
the described partial stock-to-cash API/FIFO/GL oracle, byte-identical eighteen-table
unsupported-operation refusal, and supported single-register lifecycle on the
recorded local environment. It does not close any full mandatory cycle, prove
browser interactions, measure human time savings or qualify a stable release.

The subsequent complete unchanged native release authorization file plus new
`tests/test_enterprise_program_hcm_migration.py` collected fifteen cases: fourteen
passed, one failed in 249.42 seconds, with zero skipped/xfail/xpass. The original
cross-entity API and direct-SQL SELECT/UPDATE/INSERT refusal now passed. Independent
empty 0156→0155→0156 roundtrip, populated downgrade refusal with exact retained
balance rows, and missing organization/entity invisibility also passed. The
remaining failure was legitimate HR balance provisioning for an in-scope employee
with no linked user: a new check incorrectly equated unbound identity with foreign
scope. Personal access/review for unbound employees must remain denied while HR
object scope is checked separately. That correction and final acceptance remain
pending; the negative command is retained as `qa-program-hcm-complete`.

Independent quality-constructor checks passed three cases in 1.11 seconds
(`qa-program-quality.log`): initialization preserves the caller's transaction,
rollback removes its uncommitted sentinel, and denied final DDL leaves no partial
quality schema while retaining the caller's pending rows until caller rollback.
This establishes transaction handling for that SQLite constructor only; it does
not qualify inventory quarantine, rework valuation or manufacturing integration.

After separating visible employee scope from personal user binding, final
independent native acceptance `qa-program-hcm-final` passed all fifteen cases in
133.33 seconds with zero skipped, xfailed or xpassed. The unchanged complete
release authorization file and new migration oracle retain both negative and
legitimate in-scope behavior. The command was:

```powershell
$env:RELEASE_NATIVE='1'
& output/release-blocker-20261025/venv312/Scripts/python.exe `
  output/assurance-20261026/run_evidence.py qa-program-hcm-final `
  output/release-blocker-20261025/venv312/Scripts/python.exe -m pytest `
  -p tests.mandatory_native_gate -o addopts= -q --tb=short `
  tests/test_release_authorization_postgres.py `
  tests/test_enterprise_program_hcm_migration.py `
  --junitxml=output/assurance-20261026/qa-program-hcm-final.xml
```

This closes the described HCM identity/entity admission safety regression,
including direct native SQL, migration roundtrip and populated downgrade
retention. It does not supply the attendance/leave/payroll/GL/reporting linkage
missing from mandatory cycle 3. Historical failures above remain retained.

Navigation review independently ran `src/navigation-access.test.tsx`: eight tests
passed in 2.21 seconds, retaining fifty-three destinations across eight groups.
The milestone aliases initially admitted users holding only `finance_core.read`,
although source reads require project read/manage. Agent C corrected that map;
financial binding commands continue to require their separate server policy.
Client navigation is a visibility convenience, not an authorization boundary.

Capacity persisted-data QA found another silent restriction bypass: a stored
blackout string `20261026` was accepted by Python's ISO parser but did not equal
the booking date `2026-10-26`, so the blackout check permitted the reservation.
The original successful adversarial booking is retained in
`qa-program-capacity-date-variant.log`. Agent A added canonical date spelling
validation to the existing PostgreSQL decoder and preserved explicit empty
arrays, canonical dates, and exact integer weekdays. Invalid values produce the
safe `capacity_persisted_data_invalid` code without echoing stored contents.

Final independent `tests/test_enterprise_program_capacity_quality.py` passed
three real PostgreSQL cases in 13.05 seconds with zero skips/xfail/xpass:
object-shaped blackout JSONB, boolean weekday JSONB and compact-date blackout
all refused booking while retaining byte-identical reservation rows. The
command receipt is `qa-program-capacity-final.json`, with matching log/XML.
Focused decoder, API and SQLite transaction regressions passed forty-eight
cases in 5.67 seconds. This qualifies the described persisted restrictions and
booking refusal only, not manufacturing cycle completion, parser resource
bounds or throughput.

The same canonical date requirement was subsequently enforced at domain input
for both calendar blackouts and reservation dates, so an API write cannot create
data the PostgreSQL reader must reject. Independent domain/decoder/API/SQLite
transaction regression execution passed seventy-three cases in 40.28 seconds
(`qa-program-capacity-domain-final.log`).

Broad-baseline fixture follow-up preserved every original isolation, financial
arithmetic and audit-chain assertion in `test_postgres_enterprise_integration.py`.
Its relational adapter now tracks each of the five distinct transaction settings;
caller tenant switches are explicit and a mismatched repository is explicitly
refused. Repository helper tests enter the current context manager with required
capabilities and still demand the exact 503 refusal. The native fixture uses the
configured host/port and selects its real source workspace instead of assuming
port 55432 and unbound workspace authority. These changes produced six passing
mandatory native cases in 13.82 seconds, zero skipped/xfail/xpass, in
`qa-enterprise-integration-accepted`.

The legacy milestone/elimination helpers create balanced canonical **drafts** of
1,000,000 and 100,000 minor units. New assertions require both entries to remain
Draft and actual posting-effect count to remain zero. Posted accounting is proved
separately by governed bridge tests; this fixture is not promoted into a posted
full-cycle claim. Original failures and a temporary QA Row-versus-tuple assertion
mistake remain retained in the predecessor receipts.

Independent full-file checks of Agent A's remaining assistant/authenticated-data
and five-setting scope fixture corrections passed thirty-three cases in 7.48
seconds (`qa-broad-fixture-review.log`). They retain injection/refusal assertions,
server-owned source selection, unchanged ledger/effect rows and parameterized
transaction-local settings; no production behavior was changed for those fixes.
