# Original partial-credit contracts and customer parent locks

Date: 2026-10-14. Status: accepted for the bounded contracts below.

The existing commercial collection source locked an approved invoice before
receipt posting subsequently acquired its customer. Customer returns already
acquire customer before invoice. A real approved collection waiting on a held
customer therefore retained the invoice needed by the original-return source.
The new native regression observes the actual PostgreSQL blocker and requests
that invoice with NOWAIT: the unchanged production baseline rejects with
LockNotAvailable. Acquire the immutable approved invoice's customer first,
then let the existing operational owner lock and validate the invoice. Do not
alter authorization, statement timeouts, transaction isolation or native posting.

Require the initial identity snapshot to be Approved/PartiallyPaid/Paid before
locking its customer. Draft/Submitted identity is mutable and is already refused
by the operational owner. Keep its existing operational_source_state_invalid
code/message, while Paid still reaches the existing positive-residual rejection.
The two new native cases hold the mutable source's customer and require refusal
to complete while that lock is still held, with unchanged invoice and zero effects.

The affected native collection/return cohort passes 27 cases on source00929829.
Its new case posts the real approved collection after the held parent releases:
eight GL lines, debits=credits70000, AR44000, cash1000 and retained allocation1000.
This is a bounded parent-lock correction; it does not prove universal SQL
deadlock freedom or a throughput improvement.

True partial merchandise returns require new cumulative ownership. The pure
Domain contract pins original scope, invoice, operational revenue plan, immutable
revenue/COGS snapshots and reviewed FIFO consumption order. It requires explicit
tax, lot, serial and captured currency facts. The first scope supports zero tax,
untracked base UOM and functional currency, at most32 original consumptions and
256 history events. Select the next unreturned original prefix, never an order
derived from layer UUIDs. Revenue and original cost portions must be positive
integral minor amounts; refuse implicit rounding, zero effects and over-return.

Recompute the entire append-only return/collection/refund history. For original
gross G, cumulative credit C, collections L and refunds F, receivable is
max(G-C-L,0), gross refund entitlement is max(C+L-G,0), and outstanding refund is
that entitlement minus F. New credits release receivable first. Collections and
refunds respect these respective residual caps; source/history fingerprints and
expected versions reject stale plans.

The posting builder derives unapproved correction templates using existing
Finance Posting validation and original accounts, dimensions, currency and
journals. It emits Revenue debit/AR and explicit RefundLiability credits, plus
Inventory debit/COGS credit. Zero AR/liability lines are omitted. It creates no
entry ID, full inverse, approval or native posting. New date/period/reason and
liability chart pin are explicit requested inputs. A content fingerprint does
not establish database ownership, account authorization or an open period.

Native CR2 must use additive source-owned correction effects on the existing
ledger/cost layers. Preserve full finance inverse uniqueness and the existing
active full valuation reversal constraint. Extend both cost-layer and physical
receipt history guards with reciprocal source-owned evidence, then admit the
same connection/tenant before financial effects. Preserve immutable invoice
totals/lines/receipts and OLD/NEW allocation identity/delta. AR, aging, exposure,
collections and native credit admission must share one per-invoice residual
contract. Full CR1 and CR2 claims must reciprocally exclude incompatible states.
Current authority precedes command/source waits; parent/child lock order must
also account for direct SQL and implicit FK/trigger locks.

No revision0147, PostgreSQL partial-credit table, API or Studio command is
introduced here. CR1 remains the implemented whole-tranche stock return with
partial cash refunds. Pure tests, including seven independent integer/Fraction
vectors and isolated optimized-Python guards, establish the arithmetic/template
contract only. Native CR2 admission, migration/restore, concurrency, authorization,
audit/outbox and bilingual operational acceptance remain required.

Rollback: revert the additive pure contracts and their packaging declarations;
the parent-lock correction has no schema change and may be reverted independently.
Historical source-qualified failures and positive receipts stay retained.
