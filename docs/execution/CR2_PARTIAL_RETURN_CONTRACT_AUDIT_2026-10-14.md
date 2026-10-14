# CR2 partial customer return contract audit

Status: proposed arithmetic contract only. No CR2 domain, database, native posting,
API, Studio or migration has been implemented. Audited on owned merge
`f19e8bb8c9411332dcbb31ca8a71dc05d0448972`; the existing CR1 contract remains unchanged.

CR1 already owns whole-tranche return and independently governed partial **cash
refunds**, not partial returned stock quantities. `credit_entitlement` credits all
original revenue, restores all original COGS and owes all collected cash.
`customer_return_active_source` allows one noncancelled Return per source;
`customer_return_source_available` excludes other active valuation reversals.
`PostgresCustomerReturnsRepository._restore` copies every original consumption,
and post cancels the original invoice only after the complete native effect.

The reusable facts are the unique stock-order/invoice relationship, original
single-line native delivery, frozen FIFO issue allocation order, immutable
consumptions/layer IDs, original posted revenue/COGS snapshots and dimensions,
captured currency policy, native collection evidence and three-human governance.
`customer_return_source` sorts consumptions by layer ID; a partial allocation must
instead pin the original reviewed FIFO issue order, not infer chronology from IDs.
Landed costs already capitalized in the original consumption remain part of cost;
supplier charge invoices and payments are not repriced or reversed by a return.

Three shared boundaries require an approved finite extension before native CR2:

1. Valuation reversal approval requires a full opposite movement, full document
   value, all original consumptions and exact whole GL inverse. Its active-original
   unique index admits only one reversal per valuation document. A partial Restore
   must have an explicit owner branch and structural source pins, with cumulative
   per-consumption quantity/value bounded by the original. Keep full CR1 and generic
   inverse guards intact. Reusing native Restore rows can preserve the existing
   cost-layer equation; adding a second valuation ledger is unnecessary.
2. Finance Posting requires exact full reversal snapshots and one committed
   `reverses_effect_id` per original. Partial credits cannot pretend to be full
   reversals. Use separately reviewed source-owned correction entries and an
   immutable original-effect FK, with exact original accounts, dimensions and
   policy. A finite reserved CR2 participant must admit the same connection,
   tenant and entry before posting; existing full-reversal uniqueness stays intact.
3. Native AR, aging, customer exposure and collection admission use
   `total_minor - allocations`; only terminal CR1 Cancelled projection subtracts a
   credit. CR2 needs one consistent additive credit projection and native allocation
   cap while preserving original invoice totals, lines, receipts and allocations.
   An allocation UPDATE must retain OLD tenant/ID/invoice/receipt and refuse decrease,
   delete or movement between sources. Pin the actual OLD/NEW delta, not a caller sum.

Proposed first scope: one unique stock tranche/invoice, one untracked item and
original base UOM/location/entity, zero tax and functional currency. One pending
claim serializes CR1, CR2 and collections. Prepared/reviewed cancellation releases
only that claim; posted history stays immutable. Lock current human/role/permission
and grants before source waits, then sorted parent/source/pool/physical/layer locks,
and repeat complete amount/source checks. Replay retains the original actor/body/
phase/native receipt, independently of later authorized credit or collection events.
Unowned collection histories must refuse until their original cash/effect membership
is explicitly supported; invoice-wide collections cannot be assigned wholesale to
a subset of multiple invoice tranches.

The proposed `exact-additive-original-consumption-prefix-v1` selects the next
unreturned prefix of the original reviewed consumption order. Each selected
`original_value * selected_quantity / original_quantity` and original revenue
portion must be a positive integer minor amount. Nonintegral/zero portions refuse;
existing outbound HALF_EVEN allocation does not implicitly approve a new return
rounding rule. A future cumulative remainder policy needs a separate explicit
contract and zero-value/native-effect decision.

For original gross G, current retained collections L and already posted credits C,
current AR is `max(G-L-C,0)`. A new credit d reduces AR by `min(d,current_AR)` and
creates refund liability for the remainder. Restore COGS from the selected original
consumption portions, independently of this AR/refund split. Original receipts stay
retained. Collections between returns may not exceed credit-adjusted AR; posted
refunds may not exceed the retained liability. Current authority covers every
exposed original value and unit price with its captured precision, not the small
selected return alone.

`tests/fixtures/customer-partial-return-design-v1.json` contains seven hand-authored
planned vectors: unpaid, partly collected, paid, two original layers, collection
between returns, KWD3 with quantity scale3 and JPY0. The standalone integer/Fraction
test derives each portion and customer balance without accounting-engine imports;
16 cases passed in `output/cr2-planned-exact-additive-vector-final-v2.xml` including
over-return/collection/refund, duplicate originals, nonadditive cost/revenue and
boolean/float refusal. These are arithmetic design evidence, not native acceptance.

Audited source pins: customer-return schema `54d8645c`, native valuation reversal
`baab1eea`, Finance Posting adapter `870a258a`, posting schema `6d073713`, native AR
`809a05f8`, collection schema `7bfaa8ec`, original stock schema `1d189cce`.
Root owns the shared hook design, migration allocation and concrete implementation
approval. No revision 0147 or shared source relaxation is allocated by this audit.
