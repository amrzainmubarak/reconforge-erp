# Whole customer returns and partial cash refunds

CR1 supports the complete delivered tranche of an original zero-tax,
functional-currency native stock invoice. Original quantities, FIFO cost,
invoice total, collections and postings remain available as retained source
evidence. Partial return quantities, taxed/foreign sources and cash-account
changes are refused by this bounded contract.

Select **Customer returns**, sign in, verify privileged authority, and apply
the exact workspace/organization/entity IDs. The maker supplies the original
delivered stock-order ID, an open fiscal period, posting date no earlier than
the original invoice, an active functional cash journal, a distinct native
customer-refund liability account, the original collected cash account and
a reason. **Prepare whole original return** reserves the original residual
and builds the original COGS/revenue inverses plus a collected-amount liability
entry. No stock or financial effect exists at this phase.

A different authorized human selects the retained plan and reviews its
source digest. A third human posts the complete native effect. In one ACID
transaction the system restores original FIFO quantities/cost, posts the
original inverse entries, reclassifies already collected AR to refund
liability, marks the original invoice credited, and records immutable
actor/audit/outbox/command evidence. The UI verifies the retained canonical
plan hash and renders native original/effect identifiers and exact amounts.

For a posted credit, the current balance endpoint shows original collected
refund entitlement, cumulative posted refunds and remaining liability.
Prepare one exact-minor-unit installment, review with a second human and
post with a third. It reduces only the original liability and original cash
account. Finish or independently cancel the current unposted installment
before preparing another. At most 200 refund plans are retained per credit.

An independent human can cancel only an unposted plan; after review this
human must differ from maker and reviewer. Cancellation retains original
draft/validated GL and review evidence and releases only the pending claim.
Posted credits/refunds cannot be cancelled. Prepared/reviewed plans require
an open fiscal period for this lifecycle.

All actions use `/api/v1/customer-returns/plans`: POST prepares a whole source,
GET lists scoped retained plans, GET `/{id}` reads exact native evidence,
POST `/{id}/review`, `/post`, `/cancel` advance governance, POST
`/{return_id}/refunds` prepares an installment and GET `/{return_id}/balance`
reads current liability. Send exact decimal strings in refund `amount_minor`.
The server derives scope from authorized headers; do not send client scope
or returned quantities in the body. Prepare requires read authority for
sales/receivables/inventory/finance plus sales.manage, receivables.manage,
inventory.valuation.manage, finance_core.manage/reverse. Review requires
sales.approve, inventory.valuation.approve, finance_core.validate/reverse;
post requires sales.manage, receivables.manage, inventory.post,
inventory.valuation.approve, finance_core.post/reverse; cancellation requires
sales.approve and finance_core.validate, in addition to those read grants.
Current persisted permissions, scope, amount policies and step-up apply on
every mutation and retry.

After response loss or a server/transport failure, retry the **same retained
command**, same actor, body and digest. The UI freezes scope and request while
the outcome is unknown. An old prepare/review ACK still reports its original
phase; refresh native evidence to learn later state. Successful post/cancel
ACKs remain visible if a follow-up read fails. Permission revocation may
refuse a formerly authorized retry; escalate through current authority.

Database writes that cancel without the complete inverse, change source
quantities/cost/dimensions, append extra collection or separate a refund from
its liability/GL are rejected by native SQL closure. A rejected transaction
has no committed partial stock, AR, cash, GL, audit or outbox result.
Ceilings are 1,000 original FIFO consumptions, 9e18 exact minor-unit turnover,
one pending refund and 200 retained refund plans. Inspect a rejected source
instead of substituting zeros or removing a check.

Back up and restore through the existing PostgreSQL operator procedure before
upgrade. Revision 0126 follows 0125. Empty CR1-owner downgrade is supported;
any retained plan, including cancelled drafts, refuses history-discarding
downgrade. Preserve failed upgrade/restore diagnostics. Populated rollback
requires the verified pre-upgrade database backup; validate source/effect,
nonowner FORCE RLS, head, row/function fingerprints and SQL tamper refusal.
