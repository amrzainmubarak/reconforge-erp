# Inventory Core Movement Ledger

ReconForge includes an experimental local inventory-control foundation for units of measure, stock/consumable/service item references, warehouses, hierarchical locations, lot/serial references, exact-quantity movements, derived on-hand balances, deterministic control exceptions, governed counts, reorder advice, FIFO valuation evidence, and exact valuation reversal. The movement ledger is backed by migration 9; [inventory planning](inventory-planning.md) is migration 10; FIFO valuation is migration 11; and its exact-mirror reversal is migration 12 in the same `inventory.core` runtime module.

This is a local control ledger. `Posted` means included in ReconForge's local on-hand calculation only. Posting a movement does not update a source ERP, reserve stock for an order, execute fulfillment, value stock, create accounting entries, or certify physical inventory. Monetary FIFO valuation is a separate explicit workflow; its approval prepares only a Finance Core Draft.

## Initialize or upgrade

```bash
reconforge db backup --db output/reconforge.db --output output/pre-v11-backup
reconforge db migrate --db output/reconforge.db
reconforge modules show inventory.core
reconforge modules validate
```

Migration 9 is additive. It does not import, rename, reinterpret, or delete existing `stock_moves.csv` files. Those files remain user-provided canonical exports for reconciliation. New inventory records live in separate SQLite tables and are created only through explicit inventory commands/API calls or local code.

Restore uses the backup's source schema before applying current migrations. Keep and verify a pre-upgrade backup when upgrading an important local database.

## Configure inventory masters

Create the organization, legal entity, and fiscal period first. An `EA` unit with zero decimal places is created deterministically for each workspace. Additional units declare fixed precision:

```bash
reconforge inventory unit-upsert --db output/reconforge.db \
  --code KG --name Kilogram --category Weight --decimals 3

reconforge inventory item-upsert --db output/reconforge.db \
  --code MAT-01 --name "Synthetic material" --organization SYN \
  --unit KG --type Stock --inventory-account 1400

reconforge inventory warehouse-upsert --db output/reconforge.db \
  --code MAIN --name "Main warehouse" --organization SYN --entity EG01

reconforge inventory location-upsert --db output/reconforge.db \
  --warehouse MAIN --code STOCK --name Stock --organization SYN
```

`inventory_account` is an optional local Finance Core account reference for movement-only workflows and is required before an item can be valued. Saving an item or posting a movement never creates an accounting entry; only separate valuation approval prepares a Finance Core Draft.

## Lot and serial tracking

Set `--tracking Lot` or `--tracking Serial` on the item, then register references explicitly:

```bash
reconforge inventory lot-upsert --db output/reconforge.db \
  --item SER-01 --code SN-001 --organization SYN
```

- Untracked items reject lot/serial references.
- Tracked items require an active matching reference on each movement line.
- Serial lines require exactly one unit.
- Local posting prevents the same serial from producing more than one on-hand unit.
- Manufacture and expiry dates are optional reference metadata; expired positive stock is surfaced as a control exception.

This foundation does not implement barcode scanning, variants, automatic lot creation, quality release, or regulatory traceability certification.

## Create and post a movement

Movement lines use exact decimal strings and `WAREHOUSE/LOCATION` references:

```json
{
  "lines": [
    {
      "item_code": "MAT-01",
      "quantity": "10.125",
      "to_location": "MAIN/STOCK",
      "description": "Synthetic local receipt"
    }
  ]
}
```

```bash
reconforge inventory movement-create --db output/reconforge.db \
  --number RCV/2026/0001 --type Receipt --organization SYN --entity EG01 \
  --period-id PER-... --date 2026-07-05 --description "Synthetic receipt" \
  --reference SYN-RECEIPT-001 --lines inventory-lines.json

reconforge inventory movement-post --db output/reconforge.db \
  --movement-id MOV-... --reason "Independent local receipt review"

reconforge inventory on-hand --db output/reconforge.db \
  --organization SYN --entity EG01
```

Movement direction is explicit:

| Type | Source | Destination |
| --- | --- | --- |
| Receipt | Empty | Required |
| Delivery | Required | Empty |
| Transfer | Required | Required and different |
| Adjustment | Exactly one side | Exactly one side |

## Deterministic controls

- Quantities arrive as decimal strings or integers and are stored as integer scaled units using each UOM's immutable 0–6 digit precision.
- Draft persistence and posting recheck organization, entity, period, item, UOM, warehouse, location, and lot/serial scope inside one SQLite write transaction.
- Movement dates must remain inside an `Open` fiscal period.
- Protected locations reject posting or voiding that would produce negative on-hand stock.
- Locations can explicitly permit negative stock for controlled exception workflows; negative rows remain visible and generate `INV-NEGATIVE-STOCK`.
- Active stock items without an inventory-account reference generate `INV-MISSING-ACCOUNT`.
- Positive stock in an expired lot generates `INV-EXPIRED-STOCK` for the selected deterministic as-of date.
- Known local users cannot post movements they created.
- SQLite triggers enforce `Draft -> Posted -> Voided`, require review metadata, and make non-Draft headers and lines immutable.
- Sensitive mutations append sanitized events to the local audit hash chain.

Exceptions are deterministic rules, not opaque AI or statistical risk scores.

## Permissions

| Permission | Default roles | Scope |
| --- | --- | --- |
| `inventory.read` | admin, controller, preparer, reviewer, auditor-readonly | Read masters, movements, balances, exceptions, summary, and snapshot |
| `inventory.manage` | admin, controller, preparer | Manage inventory masters and Draft movements |
| `inventory.post` | admin, controller, reviewer | Post or void movements, subject to known-user creator/poster separation |

Trusted labels such as `local-cli` preserve single-user local compatibility and remain visible in audit events. SoD enforcement applies when the actor resolves to a stored local user.

## Local contracts

- `docs/schemas/inventory_movement_lines.schema.json`: strict CLI movement input.
- `docs/schemas/inventory_core_snapshot.schema.json`: bounded path-free master/movement-header snapshot.
- `docs/schemas/inventory_on_hand.schema.json`: exact local balance response.
- `docs/schemas/inventory_control_exceptions.schema.json`: explainable derived exceptions.
- `docs/schemas/studio_inventory_control.schema.json`: bounded synthetic-only modern Studio projection.
- `docs/schemas/inventory_count_session.schema.json`: exact count-session detail.
- `docs/schemas/inventory_planning_snapshot.schema.json`: bounded count/rule snapshot.
- `docs/schemas/inventory_reorder_signals.schema.json`: deterministic reorder advice.
- `docs/schemas/inventory_valuation_document.schema.json`: detailed FIFO valuation and consumption evidence.
- `docs/schemas/inventory_valuation_snapshot.schema.json`: bounded policy/document/open-layer snapshot.
- `docs/schemas/inventory_valuation_reversal.schema.json`: detailed exact reversal and immutable layer effects.
- `docs/schemas/inventory_valuation_reversal_snapshot.schema.json`: bounded reversal lifecycle snapshot.

```bash
reconforge inventory summary --db output/reconforge.db
reconforge inventory snapshot --db output/reconforge.db > inventory-snapshot.json
reconforge inventory control-exceptions --db output/reconforge.db \
  --organization SYN --entity EG01 --as-of 2026-07-31
```

Snapshots and public exports omit database paths, source-export paths, credentials, sessions, and evidence locations. List commands default to 500 rows and accept bounded `--limit` and `--offset` values.

## Authenticated API

Read routes:

- `GET /api/v1/inventory/summary`
- `GET /api/v1/inventory/snapshot`
- `GET /api/v1/inventory/units`
- `GET /api/v1/inventory/items`
- `GET /api/v1/inventory/warehouses`
- `GET /api/v1/inventory/locations`
- `GET /api/v1/inventory/lots`
- `GET /api/v1/inventory/movements`
- `GET /api/v1/inventory/movements/{movement_id}`
- `GET /api/v1/inventory/on-hand`
- `GET /api/v1/inventory/control-exceptions`

Mutation routes:

- `POST /api/v1/inventory/units`
- `POST /api/v1/inventory/items`
- `POST /api/v1/inventory/warehouses`
- `POST /api/v1/inventory/locations`
- `POST /api/v1/inventory/lots`
- `POST /api/v1/inventory/movements`
- `POST /api/v1/inventory/movements/{movement_id}/post`
- `POST /api/v1/inventory/movements/{movement_id}/void`

Request objects reject unknown fields. API pages default to 500 records, cap at 1,000, and return pagination metadata where applicable.

## Current limitations

- A bounded FIFO valuation, exact whole-valuation reversal, and Finance Core Draft bridge are implemented separately; AVCO, standard cost, landed cost, partial/chained reversal, purchasing/manufacturing costing, foreign-currency costing, automatic entry validation, and source-ERP posting are not.
- Governed single-location count sessions and deterministic reorder rules are implemented as a foundation; blind/zero-balance count schedules, reservations, availability promises, picking, packing, shipping, demand planning, and procurement are not.
- Warehouse/location codes are local master references; there is no barcode/mobile scanning workflow.
- `Voided` removes a movement from current local on-hand calculations and is allowed only when protected-location and serial constraints remain valid. A movement with Approved valuation evidence cannot be voided; correction uses a separately Posted exact compensating movement and migration-12 valuation reversal. An Approved reversal's compensating movement is itself protected evidence and cannot be voided.
- On-hand values derive from the local movement ledger only. They are not authoritative source-ERP quantities unless the operator deliberately imports and reconciles complete source data.
- Existing export-based stock-to-GL reconciliation remains separate and unchanged.
