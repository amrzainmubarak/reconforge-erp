# Open-source financial design references and executable adoption

Reviewed official sources on2026-10-03. This is an engineering reference matrix,
not vendor interoperability, customer evidence, performance comparison or a
claim that ReconForge has implemented every referenced workflow. Source code
and third-party binaries were not imported in this research increment.

| Primary reference | Verified subject | ReconForge application | Current evidence boundary |
| --- | --- | --- | --- |
| [TigerBeetle transfer reference](https://docs.tigerbeetle.com/reference/transfer/) and [corrections](https://docs.tigerbeetle.com/coding/recipes/correcting-transfers/) | Financial transfers remain immutable; correction adds a linked financial event rather than altering the original. | Retain original reviewed posting effects, independent reversal review and source-bound replay. | PROD009/ADR0811 is tested on SQLite/PostgreSQL; this does not add TigerBeetle as a storage backend. |
| [TigerBeetle two-phase transfers](https://docs.tigerbeetle.com/coding/two-phase-transfers/) | Reservation and resolution are separate immutable events; one pending transfer cannot resolve repeatedly. | Future internal supplier-payment lifecycle should distinguish preparation/reservation, reviewed effect and external settlement observation. | AP payment aggregate is absent; the pending-transfer contract is a design input only. |
| [ERPNext perpetual inventory](https://docs.frappe.io/erpnext/perpetual-inventory) | Receipt increases inventory against goods-received-not-billed; delivery moves inventory cost to cost of goods sold; invoicing clears the appropriate commercial liability/receivable. | Specify first reviewed InventoryReceipt bundle and subsequent AP recognition/delivery/AR/cash bundles with exact independent journal answers. | PROD010/011 specification exists; the current valuation bridge produces Finance Drafts and is not an integrated operational cycle. |
| [ERPNext GL documentation](https://docs.frappe.io/erpnext/general-ledger) | Ledger detail traces financial effects to the source business voucher; subledger reports answer different outstanding-item questions. | Keep canonical source links and account drill-down; compare exact AR/AP/Inventory outstanding totals with operational effects after integration. | PROD032 provides verified effect/entry/period/date/line drill-down; trade source links remain future work. |
| [PostgreSQL16 row-security documentation](https://www.postgresql.org/docs/16/ddl-rowsecurity.html) | Referential integrity checks operate independently of row visibility; backups must not silently filter necessary rows. | Enforce captured AR customer/document monetary affinity with database constraints, alongside current RLS and native restored-scope checks. | PROD033 composite-affinity constraints are under implementation and independent raw-write testing. Existing posting native restores are separately verified. |

The architecture remains a modular monolith with Community SQLite and hosted
PostgreSQL adapters. These references inform invariants and test questions;
they do not justify adding another production database or replacing the current
transaction owner with a distributed transaction protocol.

The official [TigerBeetle license](https://github.com/tigerbeetle/tigerbeetle/blob/main/LICENSE)
identifies Apache2.0, while [ERPNext's source license](https://github.com/frappe/erpnext/blob/develop/license.txt)
identifies GPLv3. This increment uses independently written implementation and
synthetic test cases; ReconForge's existing MIT license is unchanged. A future
source/binary adoption must separately pin the exact upstream commit, record
its license/NOTICE, and satisfy the repository's dependency review gates.

The first independent accounting specification uses minor units: receipt10
units/total12000 gives DrInventory12000/CrGRNI12000. A complete future cycle
starts with cash100000, purchases10@1200 and sells4@2000; the expected end
state is inventory6/value7200, cash96000, AR/AP/GRNI0 and profit3200.
These are arithmetic acceptance targets, not observed implementation outputs.
Real effect atomicity, current human approval, scope/policy affinity, exactly
one business effect under retry, and reversal without orphaned stock/GL are
release prerequisites. PROD036 currently closes a reproduced SQLite ownership
gap before that bundle is implemented.

The already pinned IBM AMLSim45-row workload remains a separately licensed,
executed reconciliation input with an independent fault oracle. It does not
stand in for customer transactions, millions-of-record scale, realized savings
or independent auditor acceptance. Those outcomes retain separate gates.
