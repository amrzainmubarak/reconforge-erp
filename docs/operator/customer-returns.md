# Customer returns and governed cash refunds

CR1 supports the complete delivered tranche of an original zero-tax,
functional-currency native stock invoice. Original quantities, FIFO cost,
invoice total, collections and postings remain available as retained source
evidence. Partial return quantities, taxed/foreign sources and cash-account
changes are refused by this bounded contract.

Original FIFO cost includes any retained landed-cost allocation already
capitalized into the delivered layers. The credit restores that original
charged cost; it does not recalculate charge allocation or reverse the
supplier's historical charge payment. Inspect the original consumption,
landed-cost evidence and native COGS inverse together.

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

The current amount policy must admit the full original credit turnover:
invoice gross plus original COGS plus already collected cash. Refund reads,
actions and retries repeat this parent authorization, even for a small
installment. Native stock-source evidence also requires authority over the
larger of original sale value and retained COGS. These checks use the retained
original currency precision; changing a live currency catalog cannot reduce
the authority required to disclose or act on historical amounts.

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

## Native partial merchandise corrections (CR2, experimental)

Revision0147 adds a correction owner over the existing Stock/FIFO, AR, cash and
Finance Posting engines. Revision0148 adds the separately versioned remaining-value
policy and its immutable allocation witnesses. The module remains experimental;
source-qualified native and HTTPS/restore receipts do not replace the final
cohesive CI gate. Track acceptance and the open tax/FX dependency in
`docs/execution/ENTERPRISE_COMPLETION_MASTER_MATRIX.md`.

### Choose the retained source protocol

In **Customer returns**, use **Partial return cycle** for the existing v1 contract,
or **Partial return with remainder allocation** for the new v2 contract. Supply
an eligible original Stock order, fiscal period/date, refund liability and cash
references, reason and an exact positive `quantity_scaled` string. The source
balance exposes its retained quantity precision: at precision3, returning1.25
base units requires `quantity_scaled` equal to `"1250"`. Do not send a decimal
quantity, a JSON float, or a client-selected allocation/rounding policy.

The server fixes `remaining-original-v1` when a new source is born through v2.
An existing v1 source and its commands keep v1 semantics; opening v2 does not
upgrade that history. V1 lists only legacy plans and refuses v2 get/balance or
mutation with an explicit protocol conflict. V2 reads a closed v1/v2 union, but
commands and retries must use the retained plan's original route and protocol.
The Studio follows that route automatically without changing an unknown command.

Both protocols expose `/api/v{1|2}/customer-partial-returns/plans`, exact
`/plans/{id}` reads, `/plans/{id}/review`, `/post`, `/cancel`,
`/plans/{posted_return_id}/refunds`, `/plans/{posted_original_id}/reversals`,
and `/sources/{source_order_id}/balance`. Mutations require current human
permissions, step-up, the authorized workspace/organization/entity and exact
command/version/digest. Scope comes from the server-authorized headers.

### Quantities, revenue and cost

The bounded source is one native delivered Stock tranche, Stock or Consumable,
zero tax, functional currency and untracked base units. V1 requires positive
proportional revenue and cost portions that resolve to integral minor units;
nonintegral portions refuse. Native v2 requires the retained revenue policy
`ROUND_HALF_UP` and calculates from the active original remaining quantity/value
prefix: revenue uses that captured HALF_UP rule, cost
uses the existing FIFO HALF_EVEN rule, and exhaustion takes the final residual.
The immutable before-quantity/value witnesses and signed history conserve both
original amounts. A reversal copies the original actual amounts and witnesses;
it does not round them again using a later remaining balance.

A v2 return can have positive quantity with revenue0, cost0, one real monetary
leg or both. Only nonzero aggregate monetary legs produce GL entries; physical
receipt, exact layer restoration/witness, source ownership, maker/checker/poster, current authority,
immutable history, audit and outbox remain mandatory even when no GL entry is
created. A zero-valued portion inside a positive aggregate cost leg shares that
real aggregate effect. Do not fabricate a zero journal or treat a missing effect
as permission to skip the native physical/source controls.

The current balance reports actual allocated cash, net credits, open AR and
refund entitlement separately. Outstanding AR is `max(gross - actual allocated
cash - posted net credits, 0)`. Collections remain real native cash events;
no cash is inferred from a credit. A later credit may legitimately create a
refund liability after earlier collections. Prepare refunds only against a
posted return and the current liability, with three distinct authorized humans.
Histories retain at most256 economic events, at most32 original FIFO consumptions,
and one pending phase per source; at history256 a new preparation is refused.

### Restituted zero cost and warehouse transfers

A zero-cost resale original is admitted only through the native
`partial-return-restituted-v1` Stock issue policy and the closed
`stock-sales-restituted-cost-v1` factual evidence. The owner verifies the prior
restoration, original consumption membership, physical delivery, Approved
valuation and captured cost evidence. For total COGS0, entry/effect are explicitly
absent; a positive total still requires its real COGS effect even when one
consumption is zero. A caller flag, a digest alone or arbitrary free stock is
not sufficient admission. Old positive-source fingerprints remain unchanged.

IT1 cost-v1 and legacy cost-v2 evidence keep their original readers and
meaning. A pool containing remaining-policy corrections uses
`inventory-transfer-cost-v3`, retaining signed source history order and scoped
before-quantity/value witnesses. Legacy corrections retain their old evidence;
they are not silently tagged with the new policy. These captures and any genuine
zero-consumption admission remain subject to native transfer/source closure
and current permissions.

Cancel only an unposted correction. Prepare a governed reversal against the
exact posted return/refund; only the latest unreversed economic operation
qualifies. Any later immutable layer consumption prevents reversing a return,
even after a resale is itself returned. Original approved sale terms, invoice gross/lines, FIFO consumption and posted
financial evidence remain immutable. Current invoice status/row version and
credit-aware balance projections can change through their native owners.

### Read current AR exposure and aging

Open **Receivables**, choose the authorized workspace and review the original
invoice. **Cash receipts and allocations** shows the server's current invoice
outstanding and customer credit exposure after posted credits and actual cash
allocations. **Workspace receivables aging** is read-only: choose an aging date
and explicitly select **Read current receivables aging**. The view calls
`GET /api/v1/receivables/aging-by-currency?as_of_date=YYYY-MM-DD`, keeps currencies
separate and verifies the five bucket/item/total equations.

The selected date classifies the age of current open balances; it does not
reconstruct historical balances. Paid/zero-outstanding invoices are omitted.
This aging DTO has no captured decimal scale or exact-text monetary companions,
so Studio labels exact currency minor units and refuses unsafe numeric transport
instead of inferring two decimal places or substituting zero. Pending financial
commands block this read; scope/session changes, authority refusal and later
cash changes clear or invalidate old results. Arabic/English and RTL use the
same authoritative values.

### Retry, upgrade and rollback

After response loss, preserve the actor, route/protocol, command ID, body and
digest and retry the same retained command. Refresh native evidence to learn a
later phase. Current identity, scope, permissions and captured money authorization are
rechecked; a revoked grant can deny replay. New lifecycle/posting actions require
an open period. An authorized cached ACK returns the retained response without
reposting or reopening its original period. Refreshing is not a posting retry,
and a retained earlier ACK does not imply its phase is still current.

Revision0147 preflights original function bodies/execution metadata. Its empty
owner downgrade restores original functions; retained CR2 history, including
cancelled plans, prevents destructive downgrade. Revision0148 preserves eligible
retained v1 history, but refuses downgrade when retained v2 source/witness,
cost-v3 transfer or restituted-cost Stock issue/proof would be discarded,
including a mixed issue with positive total COGS.
Use the verified pre-upgrade populated backup/restore procedure in that case;
never delete witnesses or edit source policy to force a downgrade.

Taxed or foreign-currency original returns, tax adjustments and FX settlement
remain outside this bounded contract and explicitly refuse. No country-specific
compliance or complete M7/platform acceptance is implied by these operations.
