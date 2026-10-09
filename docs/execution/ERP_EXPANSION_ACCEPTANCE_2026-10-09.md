# ERP expansion: bounded local acceptance

The connected stock-sales, partial-purchasing, supplier-installment and classified
reporting slices passed local acceptance on clean source
`6ec9a70114edfd835386ee3b0f0085e5da1fff15`. Work starts at PR125 exact
`f24d48363817f36991239c436ae616f59d391918`, preserves PR124 ancestry, and leaves
main at `b61ea56bb9c135fda12546e173795af3c243e4fb`. Three independent managed
worktrees were integrated centrally; every sprint author and committer is Amr.

[Draft PR126](https://github.com/amrzainmubarak/reconforge-erp/pull/126) is stacked
on PR125. [Current-source hosted checks](https://github.com/amrzainmubarak/reconforge-erp/pull/126/checks)
are authoritative for the final hosted Python3.11/3.12, eleven mandatory native
shards, engine parity, object storage, HA/DR, browser, Security, Docker and CodeQL
results. This document records local acceptance separately. The
[machine-readable packet](ERP_EXPANSION_ACCEPTANCE_2026-10-09.json) binds original
reports, command logs, JUnit, sources, hashes and explicit nonacceptance packets.
Local detailed outputs are retained under `output/erp-expansion-20261009` and
are not Git-tracked. Hosted reports remain attached to their Actions runs.

## Connected capabilities

- Stock order and commercial discount → independent approval → exclusive
  reservation → frozen native FIFO issue/COGS → reviewed AR/revenue → reviewed
  full cash collection/Paid. All three financial effects require distinct
  preparer, reviewer and poster identities in the owner, Studio and deferred SQL.
- Approved purchase → repeated reviewed partial receiving → inventory/FIFO/GL
  and native goods receipts → exact quantity/price three-way matched invoice
  tranches → reviewed clearing-to-AP accrual → reviewed partial AP payments and
  native cumulative settlement. The prepared quantity reserves capacity under
  the parent lock; native effects and owner acknowledgements share one transaction.
- Reviewed explicit account classifications → balanced first-history opening →
  independent review and third-person GL posting → as-of trial balance, balance
  sheet, income statement and cash movements with source-effect drilldown and an
  independent exact-money client fold.

These reuse existing inventory, valuation, AR/AP, Finance Posting, identity,
authorization, audit and outbox kernels. The0112–0115 migrations add19 forced-RLS
owner tables; the reviewed inventory contains384 API routes and59 application
ports. No duplicate posting engine, placeholder module or live-bank execution
is introduced. Legacy native two-person publication remains compatible; only
the new owners enforce the stronger three-person policy.

## Actual local gates

| Gate on source6ec9 | Result |
|---|---|
| Native Stock/Partial Procurement and authenticated API |43 passed; zero failures/errors/skips;726.95s pytest|
| Native installments/reporting and authenticated API |25 passed; zero failures/errors/skips;878.51s pytest|
| Domain, CI ownership, parity and authorization contracts |47 passed; zero skips|
| Studio typecheck / production build |Passed;2.201s /3.446s|
| Full React |295 passed in42 files; zero skips|
| Existing ERP and expansion wire HTTPS cycles |One real case each; zero skips/flakies;131.365s /202.968s|
| Populated native dump/restore |Both compare214 tables and197 function definitions, catalog/ACL/policies/constraints/indexes; three tamper refusals each|
| Standard browser / separate actual HTTPS hosting |19 passed +9 existing external prerequisites; separate HTTPS1 passed with zero skips|
| Ruff / Mypy / Bandit / pinned Gitleaks |Passed;651 Mypy source files; zero Bandit findings; history and tracked tree scanned|
| wheel/sdist and installed origins |Real build/offline install/doctor;651 runtime modules,115 migrations,984 required source members and166 Studio members verified; the required subset is not the total sdist file count|
| Fresh Docker image |Build,651 runtime/115 migration byte checks, UID10001, no-network/read-only/cap-drop doctor and sample validation passed|
| Image SBOM/Grype/policy |0 Critical/High/Unknown;9 Medium and1 Negligible; zero exceptions|
| Bounded recovery/capacity |1000 in-memory HTTP requests and1000 synthetic SQLite queued jobs; zero errors,29ms p95,1ms aggregate query, backlog recovery passed|

Native gates use pinned PostgreSQL17.10, migration head0115 and an application
role with neither superuser nor BYPASSRLS. The actual expansion browser posts
12 effects with debit=credit187000 minor units: two stock receipts, two supplier
invoices, four installments, stock revenue/collection and opening. It retains
FIFO quantity5/value6000, assets116500, liabilities0, equity100000, unclosed
profit16500 and closing cash110500. Seven reviewed financial posting controls
are disabled for the reviewer; the third human completes each operation.

The critical cases cover current authority and tenant boundaries, concurrency,
exact command replay/lost acknowledgements, SQL publication with the Python
owner check deliberately bypassed, independent SQL rejection/complete financial
rollback, immutable history, missing/wrong account/date/currency capture,
late acknowledgement failure after GL/AP allocation, and successful safe retry.
API denials retain valid authorization evidence while leaving financial effects
and existing financial audit history unchanged. Owned processes, databases,
containers and the final image are removed after their gates.

## Verification ownership and reproduced failures

CI preserves all nine previous native shards and adds `erp-expansion` and
`finance-reporting`, with fail-closed aggregation. Generic Python profiles omit
only the two Stock PostgreSQL fixture modules; those complete modules run
unconditionally in the configured mandatory expansion shard. The executable CI
selection tests prove all native files retain exactly one owner and no case is
filtered with `-k` or deselected. Generic prerequisites and the nine standard
browser skips are not treated as successful native verification.

First merged hosted run37868853452 failed and remains failed. Its missing parity
inventory/fixture routing and asynchronous identity-scope race were repaired.
Original reviewer-publication RED probes, native source-capture failures,
first React focus failure, report contrast/keyboard failures, installment-history
field access failure, missing source-archive documents and public-contract secret
false positive remain preserved. The c80 native/security readers have explicit
interruption packets, not inferred success. On6ec9, one targeted command used a
wrong test filename and one standard-browser launch could not bind Windows
port4175; each original attempt remains unaccepted and only its affected group
was corrected. No new skip, scanner exception or weakened business constraint
was used to turn a failure green.

The local Python/npm advisory lookup remains attributed to source68cc and its
actual timestamps, with complete immutable lock/policy byte-identity binding.
Fresh current-source hosted Security audits are separate. Grype used a verified
immutable database built2026-10-07, within the existing freshness policy; the
license inventory is not an independent legal-compatibility assessment.

## Limits and rollback

Stock sales remain one untracked functional-currency line with full fulfillment,
invoicing and collection. Partial sales, customer returns/refunds/credits and a
stock inverse are deferred. Purchasing remains one untracked zero-tax line,
up to32 receipts/invoices; requisitions/RFQ, supplier quotations, supplier
returns/debit notes, multi-line tax/FX accounting remain deferred. Installments
use retained AP/cash mappings, up to200 plans/invoice and one pending; correction
needs a future inverse contract and settlement does not send a bank transfer.

Opening precedes all posted entity history. Statements are bounded recorded
business-date views with1000 effects/10000 lines and explicit classifications;
cash movements are not statutory cash-flow classifications. New treasury, FX,
assets, intercompany or consolidation completeness is not claimed. Native
same-date lexical FIFO ordering remains and can refuse later receipt sequences.
The capacity test is one synthetic local run with in-memory HTTP transport,
not ERP throughput, a soak test, distributed capacity or a production SLO.

All four owners remain experimental. Independent production/security assurance,
legal/compliance certification and physical multi-site RPO/RTO evidence remain
separate. Back up before upgrade. Empty ownership migrations can downgrade;
populated destructive rollback is refused. Use a verified full native backup
and compatible preceding runtime to restore populated deployments, preserving
immutable source and GL history.
