# ADR 0847: Original customer source credits and partial refunds

Date: 2026-10-10. Status: implementation; source-bound integrated acceptance remains separate.

CR1 adds a complete whole-delivered-tranche inverse above accepted PR129
`e07bff2a2e8197b052d53454ea85c727f7c7518e`. It uses the existing native
stock-sales source, immutable FIFO consumptions, valuation reversal effects,
AR invoices/allocations, reviewed GL posting, currency registry, identity,
audit and outbox. It creates no additional ledger or currency engine.

For an original zero-tax functional-currency invoice with gross `G`, original
FIFO cost `C` and already collected `P`, the native credit reverses exactly
the original revenue and COGS entries, restores exactly the original
consumptions, credits original AR by `G` and reclassifies `P` from AR to
customer refund liability. Thus net AR is zero, restored stock cost is `C`,
and refund liability is `P`. Each CRF1 installment `R` debits that liability
and credits the original cash account. Its cumulative amount cannot exceed
`P`. Original invoice total, allocations, receipts and financial effects
remain retained. The invoice is terminal Cancelled only with complete
credit/native stock/native GL closure; it is not silently deleted.

Preparation reserves the exact source invoice using a nullable native AR
marker. Current native collection admission refuses new allocations or
collection plans while that marker is present. Marker-null ordinary reads
and writes return before querying owner tables; no legacy-role grants widen.
Prepared/reviewed cancellation releases only this claim and retains original
drafts, review and prior command acknowledgements. Posted credits cannot be
cancelled. Refund installments have independent three-human governance.

Commands bind actor, route operation, exact request and source digest.
Every retry repeats current persisted RBAC, ABAC, scope and step-up checks.
Historical acknowledgements retain their original phase; current liability
is a separate `/balance` read. Invoker-scoped deferred SQL closure checks
native stock, original inverse snapshots/dimensions/currency, AR state,
liability/cash lines, actor separation, audit/outbox and exact commands.
Lock acquisition is period, existing canonical currency binding, native customer/invoice/source, parent/plan,
canonical stock/FIFO keys, sorted layers and sorted GL entries.

Refund evidence and lifecycle admission also repeat current authorization over
the full retained parent credit turnover. An installment amount cannot admit
the original credit or prior refund amounts that its source evidence exposes.
Original stock-sale revenue inverses are bound to the original OPS posting
effect in SQL, including Generated drafts with unrelated entry numbers.

Bounds are one complete native stock tranche, at most 1,000 original FIFO
consumptions, exact integer amounts/turnover at most 9e18, 200 retained refund
plans per credit and one unposted refund installment. Partial returned
quantities, tax-bearing sources, FX sources, mixed original cash accounts,
fees, exchange/replacement orders and arbitrary credit/debit notes remain
outside this contract. SQLite exposes no financial substitute; unsupported
backend requests fail explicitly.

Migration 0126 follows 0125, retains prior source bodies using guarded narrow
substitutions and installs FORCE RLS. Empty-owner downgrade restores those
bodies. Any retained owner history refuses downgrade; populated recovery
uses a verified pre-upgrade backup and the existing restore verifier.

Targeted independent Fraction tests, native nonowner SQL attacks, atomic
failure/retry races, original FIFO resale, API exact-money tests, bilingual
Studio response-loss tests and populated HTTPS restore are acceptance
requirements. Passing development tests on a dirty checkout does not
establish frozen-source acceptance or production readiness.
