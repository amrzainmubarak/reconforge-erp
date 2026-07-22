# FIFO Inventory Valuation Foundation

ReconForge includes an experimental, local-first FIFO valuation foundation backed by SQLite migrations 11 and 12. It values eligible Posted movements from the local [inventory movement ledger](inventory-core.md), preserves cost-layer evidence, prepares a balanced entry in the separate [Finance Core control ledger](finance-core.md), and corrects an Approved valuation through an explicit exact-mirror reversal workflow without deleting history.

The accounting bridge stops deliberately at **Finance Core Draft**. Approval of a valuation does not validate that entry, post to a statutory ledger, update a source ERP, infer a supplier invoice, or certify the resulting accounting treatment.

![Synthetic read-only FIFO valuation view](assets/screenshots/inventory-valuation.png)

## Scope and prerequisites

The current slice supports:

- FIFO only, for Receipt, Delivery, and positive or negative Adjustment movements;
- one entity currency and one active entity-scoped valuation policy per selected policy code;
- exact input total cost for every inbound movement line;
- oldest-approved-layer consumption for outbound lines, scoped by legal entity, item, UOM, and lot/serial;
- immutable Approved valuation lines, layer origins, and layer-consumption evidence;
- one balanced, Generated Finance Core Draft per Approved valuation;
- explicit Draft, Approved, and Cancelled valuation states;
- exact reversal of one Approved valuation through a separately Posted compensating movement;
- immutable `Restore` or `Remove` FIFO-layer effects and a debit/credit-swapped Finance Core Draft.

Configure organization/entity/period, Finance Core chart/accounts/journal, inventory UOM/item/warehouse/location, and a Posted movement first. Each valued item needs an active posting-enabled inventory account from the valuation journal's chart. The policy currency must match both the legal entity and journal.

Required Finance Core dimensions are not silently guessed. Policy creation and approval refuse that configuration until a future explicit dimension-mapping contract exists.

## Configure a FIFO policy

```bash
reconforge inventory valuation policy-upsert \
  --db output/reconforge.db \
  --policy FIFO \
  --organization SYN \
  --entity EG01 \
  --journal INV \
  --receipt-clearing 2100 \
  --cogs 5100 \
  --adjustment 5190
```

The account roles are explicit:

| Movement flow | Finance Core Draft debit | Finance Core Draft credit |
| --- | --- | --- |
| Receipt | Item inventory account | Receipt clearing account |
| Positive Adjustment | Item inventory account | Adjustment account |
| Delivery | COGS account | Item inventory account |
| Negative Adjustment | Adjustment account | Item inventory account |

Transfers do not create valuation documents because they do not change entity cost ownership in this foundation. Inter-entity transfers, in-transit ownership, and transfer-price accounting remain out of scope.

## Prepare and approve a receipt

Inbound cost is a per-line total, supplied as an exact decimal string. Repeat `--cost` for each inbound line:

```bash
reconforge inventory valuation create \
  --db output/reconforge.db \
  --number VAL/2026/0001 \
  --movement-id MOV-... \
  --policy FIFO \
  --cost 1=100.01

reconforge inventory valuation approve \
  --db output/reconforge.db \
  --document-id IVD-... \
  --reason "Receipt cost evidence independently reviewed" \
  --actor reviewer
```

Approval creates the receipt layer and a balanced Finance Core entry such as `IV-VAL/2026/0001`, with status `Draft`. Finance Core validation is a separate permissioned review action.

## Value a delivery

Outbound documents do not accept input cost. Approval consumes the oldest eligible Approved layers:

```bash
reconforge inventory valuation create \
  --db output/reconforge.db \
  --number VAL/2026/0002 \
  --movement-id MOV-... \
  --policy FIFO

reconforge inventory valuation approve \
  --db output/reconforge.db \
  --document-id IVD-... \
  --reason "FIFO issue independently reviewed" \
  --actor reviewer

reconforge inventory valuation layers --db output/reconforge.db --open-only
```

For example, a 10-unit receipt valued at `100.01` followed by a 3-unit delivery yields an outbound value of `30.00` and a remaining layer value of `70.01`. Values are stored as integer currency minor units; quantities are stored as scaled integers at the UOM precision. Binary floating-point cost input is rejected. If a partial issue cannot yield a meaningful positive allocation within the currency's minor-unit precision, approval fails atomically instead of inventing value.

## Reverse an Approved valuation

A reversal never edits the original movement, valuation, consumption, or Finance Core entry. First create and independently post a compensating inventory movement with the same workspace, organization, entity, item, UOM, lot/serial, quantity, precision, and line numbers. Locations must be swapped exactly. `Receipt` reverses through `Delivery`, `Delivery` through `Receipt`, and `Adjustment` through `Adjustment`; the compensating movement cannot predate the original.

```bash
reconforge inventory valuation reversal create \
  --db output/reconforge.db \
  --number IVR/2026/0001 \
  --valuation-document-id IVD-... \
  --movement-id MOV-... \
  --actor preparer

reconforge inventory valuation reversal approve \
  --db output/reconforge.db \
  --reversal-id IVR-... \
  --reason "Exact correction independently reviewed" \
  --actor reviewer

reconforge inventory valuation reversal show \
  --db output/reconforge.db \
  --reversal-id IVR-...
```

Approval applies the exact inverse of the original evidence:

- Reversing an outbound valuation restores every immutable original layer consumption, including its exact scaled quantity and minor-unit value.
- Reversing an inbound valuation removes its originating layer only when that layer is still completely untouched. If a later outbound valuation consumed it, reverse those dependent outbound valuations first.
- The generated Finance Core entry copies the original accounts and dimensions but swaps every debit and credit. It remains `Draft`; Finance Core validation is still a separate permissioned decision.
- The compensating movement and reversal Finance entry remain protected evidence after approval. Neither can be voided, and the reversal header, layer effects, finance lines, and finance dimensions cannot be silently changed.

Only one active reversal may reference an original valuation or compensating movement. Cancelling a Draft changes no layer or finance balance. Reversal-of-reversal chaining is not implemented; corrections proceed in dependency order from outbound consumers back to the inbound layer.

## Lifecycle and ordering controls

```text
Draft -> Approved
  |
  +-----> Cancelled
```

- Only a Draft can be Approved or Cancelled.
- Approval requires a documented reason and a Posted source movement.
- A known local user cannot approve a valuation they created.
- FIFO approval must proceed in movement date/order; an earlier eligible Posted movement cannot remain unvalued.
- Backdated approval is blocked after a later valuation is Approved.
- Insufficient eligible layer quantity rejects the whole transaction.
- Approved source movements remain immutable. Correction uses the migration-12 exact-mirror reversal workflow rather than deleting valuation history.
- Database triggers protect Approved headers, lines, input evidence, layer origins, consumption evidence, and layer balance transitions.
- Valuation mutations append sanitized local audit events.

Approval is atomic: valuation evidence, layer changes, the Finance Core Draft, and valuation status either commit together or roll back together.

## Permissions

| Permission | Default roles | Scope |
| --- | --- | --- |
| `inventory.read` | admin, controller, preparer, reviewer, auditor-readonly | Read policies, documents, summaries, snapshots, and layers |
| `inventory.valuation.manage` | admin, controller, preparer | Configure policies; create or cancel Draft valuations |
| `inventory.valuation.approve` | admin, controller, reviewer | Approve valuations and prepare the linked Finance Core Draft, subject to SoD |
| `inventory.valuation.reverse.manage` | admin, controller, preparer | Create or cancel Draft reversals linked to exact Posted mirror movements |
| `inventory.valuation.reverse.approve` | admin, controller, reviewer | Approve immutable layer effects and prepare the swapped Finance Core Draft, subject to SoD |

Trusted labels such as `local-cli` remain available for local single-user compatibility and are audit-recorded. Known-user SoD is a workflow control, not legal sign-off or audit assurance.

## Authenticated API

Read routes:

- `GET /api/v1/inventory-valuation/summary`
- `GET /api/v1/inventory-valuation/snapshot`
- `GET /api/v1/inventory-valuation/policies`
- `GET /api/v1/inventory-valuation/documents`
- `GET /api/v1/inventory-valuation/documents/{document_id}`
- `GET /api/v1/inventory-valuation/cost-layers`

Mutation routes:

- `POST /api/v1/inventory-valuation/policies`
- `POST /api/v1/inventory-valuation/documents`
- `POST /api/v1/inventory-valuation/documents/{document_id}/approve`
- `POST /api/v1/inventory-valuation/documents/{document_id}/cancel`

Reversal routes:

- `GET /api/v1/inventory-valuation/reversals/summary`
- `GET /api/v1/inventory-valuation/reversals/snapshot`
- `GET|POST /api/v1/inventory-valuation/reversals`
- `GET /api/v1/inventory-valuation/reversals/{reversal_id}`
- `POST /api/v1/inventory-valuation/reversals/{reversal_id}/approve`
- `POST /api/v1/inventory-valuation/reversals/{reversal_id}/cancel`

Request objects reject unknown fields. API lists default to 500 rows and cap at 1,000. Reads accept any inventory read/valuation permission; manage and approval actions require their separate permissions.

## Contracts, recovery, and Studio

- `inventory_valuation_document.schema.json` defines one detailed valuation with exact costs, lines, and FIFO consumption evidence.
- `inventory_valuation_snapshot.schema.json` defines the bounded path-free policy/document/open-layer view.
- `inventory_valuation_reversal.schema.json` defines one detailed reversal with its exact immutable layer effects.
- `inventory_valuation_reversal_snapshot.schema.json` defines the bounded, path-free reversal summary/header view.
- `studio_inventory_control.schema.json` includes allowlisted synthetic valuation, reversal, and layer records for the read-only modern Studio.
- Public DB export includes valuation policies, documents, input costs, lines, layers, consumptions, reversals, and reversal effects in `inventory.json`.
- Local backup/restore preserves all valuation and reversal tables, reconstructs lifecycle state through database triggers, and verifies layer balances against both consumptions and reversal effects after restore.

The Studio view is a synthetic, read-only projection. It displays Finance Draft references but cannot approve valuations, validate entries, access a database path, or write to an ERP.

## Current limitations

- FIFO only: no AVCO, standard cost, specific identification, negative inventory valuation, landed cost, rebates, freight allocation, or revaluation engine.
- No purchase receipt/vendor bill cost derivation, manufacturing/WIP costing, work-order absorption, scrap costing, or sales-margin engine.
- No foreign-currency conversion, exchange-rate source, remeasurement, or cross-entity ownership transfer.
- No required-dimension mapping for generated finance lines.
- No automatic Finance Core validation, statutory posting, source-ERP writeback, or direct ERP connector.
- No reversal-of-reversal workflow, partial valuation reversal, or layer-aging report yet.
- SQLite is the verified repository. PostgreSQL support remains unclaimed until a separate adapter passes repository and transaction contract tests.

This is an early-stage control-ledger foundation for local review, not a complete inventory accounting subsystem or a compliance conclusion.
