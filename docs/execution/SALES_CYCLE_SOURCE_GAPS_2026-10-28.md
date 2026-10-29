# Sales cycle source gaps — 2026-10-28

Source inspected: `c44a71110dd63f3ef2372c0bc8d451f91d3424d7`. The current
source contains independent components; it does not establish one qualified
lead-to-cash business cycle. This review and its synthetic examples are not a
live end-to-end PostgreSQL run or an assertion that any accounting entry is
wrong. Earlier partial-cycle results retain their original source and scope in
`ENTERPRISE_CYCLES_2026-10-26.md`.

## Source ownership and existing interfaces

* `reconforge/domain/crm_contracts.py` models `lead` as an opportunity stage;
  this inspection found no separate lead record or lead-to-opportunity link.
  `POST /api/v1/crm/contracts/opportunities` accepts a new opportunity with
  caller-supplied customer and organization.
* `POST /api/v1/crm/contracts/quotations` accepts an `opportunity_id`, but the
  route and the PostgreSQL quotation repository do not load or validate the
  opportunity. The `crm_quotations` table in the enterprise-module schema has
  no foreign key to `crm_opportunities` or customer/currency consistency rule.
  The current contract is workspace-scoped and existing unlinked records do
  not supply proof of the original opportunity or entity.
* Quotation conversion calls `convert_quote_to_contract` and `save_contract`.
  That path does not call stock-sales, AR or Finance posting. It is not a
  quotation-to-inventory or quotation-to-GL bridge.
* The independent `POST /api/v1/stock-sales/orders` accepts an explicit
  `StockOrder`, with no CRM quotation identity. Its PostgreSQL owner validates
  stock, customer and selected entity masters and captures source and monetary
  policy digests. Its issue, invoice and collection stages are separate
  governed operations. `tests/test_enterprise_program_stock_to_cash.py`
  creates an order directly and tests part of that path with a synthetic FIFO,
  cash and GL oracle; it does not prove a CRM origin, complete report or UI.

## Reproducible observations

The following pure domain example was executed from the repository root with
Python 3.14.6 and returned `1 2`. CRM discounts the total gross line amount
using integer half-up rounding. Stock sales discounts the unit price first,
using `per-unit-minor-half-up-v1`, then multiplies by quantity. Neither value
below is a posted entry:

```python
from reconforge.domain.crm_contracts import QuotationLineItem
from reconforge.domain.stock_sales import StockOrder

quote = QuotationLineItem(1, "ITEM", "Synthetic", 2, 1, 2500)
order = StockOrder("ORDER", "CUSTOMER", "REF", "ITEM", "MAIN", "STOCK",
                   "2", 1, "USD", "2026-10-28", "Synthetic", 2500)
print(quote.net_amount_minor, order.payload()["total_minor"])
```

The independent integer calculation is `gross=2`, CRM discount
`floor((2*2500+5000)/10000)=1`, CRM net `1`; stock net unit
`floor((1*(10000-2500)+5000)/10000)=1`, stock total `2`. The policies differ;
neither is universally chosen as correct without an explicit business policy.
Copying an approved CRM quote into stock sales must not silently substitute
one policy for the other.

An in-memory SQLite repository reproduction also confirmed that a quote can be
saved for a nonexistent opportunity:

```python
import sqlite3
from reconforge.domain.crm_contracts import CustomerQuotation, QuotationLineItem
from reconforge.infrastructure.sqlite_crm_contracts import SqliteCRMContractsRepository

repo = SqliteCRMContractsRepository(sqlite3.connect(":memory:"))
quote = CustomerQuotation("Q-MISSING", "OP-DOES-NOT-EXIST", "ws", "CUSTOMER",
    "USD", "2026-12-31", "maker", "draft",
    (QuotationLineItem(1, "ITEM", "Synthetic", 1, 100),))
assert repo.get_opportunity("ws", quote.opportunity_id) is None
repo.save_quotation(quote)
assert repo.get_quotation("ws", quote.quote_id) is not None
```

This is a local SQLite result, not a PostgreSQL reproduction. Existing
`tests/test_crm_authority_postgres_20261026.py` creates a quotation referencing
`OP` without creating its opportunity; `tests/test_release_product_crm_identity.py`
also exercises direct quotation creation without a preceding opportunity.
These tests and the current v1 contract make an unconditional new foreign key
or changed creation rule a compatibility change.

## Candidate slice and qualification gates

A versioned, opt-in operation could create a quotation from a persisted
opportunity, with an immutable source binding and snapshot rather than
retroactively assigning a source to old quotations. Its contract must verify
tenant, workspace, organization, customer, currency and allowed opportunity
state from authoritative records. Approval identity and the exact quotation
content need durable review and locking before any financial successor can
trust them; the existing `save_quotation` path can update quotation lines, and
an immutable author binding by itself is not a complete approved-price seal.

Before binding a quote to an order, explicitly version the conversion and
discount policy, retain both source and result snapshots and currency registry
interpretation, and either prove exact value conservation or reject unsupported
rounding cases. Do not silently reinterpret historical quotes. One-line stock
orders and multi-line quotes require an explicit bounded mapping and duplicate
or partial-conversion policy. Entity ownership, approval and transaction
boundaries must be proven before posting is claimed.

For a future slice, use a migrated PostgreSQL instance with a restricted role
and synthetic identities. Test the original opportunity→quotation link;
missing and foreign-tenant/workspace/organization sources; customer and
currency mismatch; unchanged exact retries; altered, duplicated and partial
requests; concurrent approvals/conversions; independent maker/checker;
rollback and restoration with populated legacy records. Verify both backend
contracts where supported and record source, dataset, policy versions and
oracle. A passing link test does not qualify the full source-to-report cycle;
the later FIFO, invoice, collection, GL, report, UI, failure and restore
journeys must be connected to the same authoritative chain.
