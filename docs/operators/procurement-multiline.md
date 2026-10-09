# Governed multiline stock purchasing

This extension adds a retained business owner to the existing native purchase
order. Each order contains 1–128 immutable native purchase lines. Each line
retains its item, exact unit precision, warehouse/location, FIFO policy, ordered
quantity, unit price and total. Amounts use integer minor units. Quantities with
different units remain separate; aggregate quantity fields in the compatibility
header are zero and Studio shows each actual line instead.

Install the complete PostgreSQL migration chain through
`0117_pg_procurement_multiline`, including the reviewed financial-installments
extension at `0115`. The migration follows `0116_pg_stock_commerce` and adds two
tables with FORCE RLS. It dispatches existing one-line owners to the original
closure without changing their permitted phases or 32-document limits.

In Studio, select the authorized organization/legal entity, verify identity,
open **New stock purchase**, and enable **Enterprise multi-line order**. Select
an active functional-currency supplier, fiscal period and journal/account
mapping. Add the actual item, quantity, price, receiving location and FIFO policy
for every line. The item catalog searches literal text and uses keyset pages of
50, allowing a configured catalog to exceed the previous 200-item picker.
Suppliers, locations and accounting reference pickers retain their existing
bounded native options contract.

The preparer submits the order and an independent authorized person approves
the native purchase order. Each receipt reserves a selected line's remaining
ordered capacity under the parent row lock. A second person reviews the native
receipt plan and a third person posts it. Receipt publication creates the
physical stock movement, FIFO valuation layer, double-entry inventory/clearing
posting and native AP goods receipt in one transaction. Posting dates must
satisfy the native stock chronology contract.

An invoice selects quantities from one or more actual order lines. Allocation
reserves only posted receipt quantities less prior invoice allocations. Exact
native three-way matching must pass with zero price, quantity and tax variance.
Approval and independently reviewed accrual post clearing to AP using the
existing financial engine. Lines must use the same receipt-clearing account;
orders in this slice use functional currency and zero tax.

Partial payments reuse the financial-installments contract against the actual
accrued native supplier invoice. The preparer, reviewer and poster must be three
distinct canonical humans. Each posted payment creates one immutable AP payment
link and the corresponding AP/cash GL effect. Pending plans prevent another
preparation on the same invoice; safe retries retain the exact actor-bound
command. No external bank transfer is performed by this contract.

Order lists use keyset pages of 25. Enterprise receipt and invoice histories
allow at most 1024 documents each and project 25 at a time. Counts, conserved
line quantities and financial totals cover the whole owner rather than only
the visible page. Command acknowledgements focus the acted document and remain
immutable. A lost or malformed acknowledgement locks subsequent writes until
**Retry the same command** is verified. Invoice payment evidence is paginated;
normal detail projects recent evidence while full paid and outstanding totals
remain authoritative. The installed payment contract retains its 200-plan limit
per native invoice.

Direct SQL cannot detach an approval, receipt, invoice, accrual or payment from
its owner. Deferred native/source closure binds typed item/unit/location/policy
references, exact native monetary and quantity states, every parent command,
the frozen acknowledgement, audit and outbox evidence. Immutable lines cannot be
changed after preparation. Roll back a failed command completely, then retry
the exact command with the same canonical actor and current authority.

An empty `0117` downgrade is supported and restores legacy guards. Populated
multiline history refuses downgrade. Preserve and verify a pre-upgrade backup
for destructive schema rollback; retain financial history and prefer a forward
correction. Supplier returns, debit notes, receipt/payment reversals, PR/RFQ,
budget commitments, configurable matching tolerances, tax and FX are separate
contracts and are not implemented by this slice.

Configured native gates are
`tests/test_postgres_procurement_multiline.py`,
`tests/test_postgres_procurement_multiline_api.py` and
`tests/test_postgres_procurement_multiline_migrations.py`; they require an owned
real PostgreSQL fixture with a non-superuser role that cannot bypass RLS. The
full integration acceptance and operational browser evidence are maintained by
the lead integration gate. The bounded limits are resource contracts, not
claims of measured throughput or independent production certification.
