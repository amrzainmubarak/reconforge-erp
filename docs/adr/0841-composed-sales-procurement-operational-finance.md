# ADR 0841: Compose Sales, Procurement and reviewed operational Finance

Date: 2026-10-08
Status: Accepted for implementation; acceptance pending integration gates

The ERP completion sprint starts at `dbad7b03` on
`amr/global-erp-completion-20261008`. It preserves the accepted platform sprint,
MIT license, local compatibility and immutable financial history. Main remains
unchanged. This decision authorizes additive operational modules, not a
production readiness or regulatory claim.

## Decision

Reuse PostgreSQL identity, scope, currency, AR, AP, FIFO, reviewed inventory
receipt, Finance posting and AP payment-link engines. Introduce a reviewed
operational source-posting port before composing Sales and Procurement. One
scoped READ COMMITTED transaction owns the source, reviewed balanced ledger
effect, allocation or settlement, command and audit. Participant repositories
use that connection and cannot commit independently. Independent human review,
exact source snapshots, current versions, original-actor replay and database
completeness guards apply. The reserved `OPS1-` namespace cannot be posted
through the generic endpoint: native AR/AP backing rows and immutable source
links must close in the same transaction. Existing Manual/Reversal and IRP1
contracts remain intact.

Build two bounded complete initial cycles:

- Service revenue: customer -> exact discounted quotation -> independent
  approval -> order -> actual service fulfillment -> AR invoice and revenue
  accrual -> cash receipt, allocation and cash/AR settlement.
- Full one-line untracked stock procurement in functional currency: supplier
  -> reviewed PO -> receipt/FIFO/inventory-clearing GL -> matched supplier
  invoice and clearing/AP accrual -> reviewed AP/cash payment and settlement.

Extend a cycle only after its actual integration gate succeeds. Partial stock
returns, tax, FX settlement, PR/RFQ, assets and banking adapters require their
own connected invariants and evidence. Amounts remain exact with explicit
currency metadata. No SQLite fallback serves a PostgreSQL operational request.

## Ownership and dependencies

Three isolated worktrees start from the same checkpoint. Finance owns its new
operational-finance module and revision0109 (down0108), plus narrowly approved
private participant/direct-admission changes in postgres_finance_posting.py.
Sales owns its new module/API/UI/tests and revision0110 (down0109). Procurement
owns its corresponding files and revision0111 (down0110). Each owns its module
manifest and operator documentation.

The lead alone owns shared API registration/authorization, policy inventories,
migration/recovery/packaging/CI inventories, Studio shell/navigation/global
messages and execution state. Integrate Finance -> Sales -> Procurement ->
shared Studio -> aggregate verification. Agents commit as Amr.

## Verification and rollback

Build related capabilities in batches. Run focused real PostgreSQL and API
gates on completed cycles. Run full Python, React, E2E, security, financial
integrity/concurrency, populated native backup/restore, performance, package,
container and CI gates on a stable integrated commit. Keep initial failures
and prerequisite limitations explicit. Add no skips or weakened security
controls to manufacture success.

Additive migrations preflight incompatible reserved identifiers. Preserve
accepted records and source links. Application rollback can remove new route
exposure while retaining populated additive schemas; destructive downgrade is
refused if financial evidence exists. Draft review records the exact verified
subject, supported boundaries and unfinished capabilities. Modules remain
experimental until their separate release gates pass.
