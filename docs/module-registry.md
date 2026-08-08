# Runtime Module Registry

ReconForge exposes a deterministic, read-only registry for capability inspection. It helps operators, maintainers, and future clients distinguish implemented workflows from foundation-stage or experimental slices without importing arbitrary plugins, touching the database, or making network calls.

The registry is metadata, not a marketplace, dynamic code loader, entitlement system, production-readiness certificate, or claim that documented roadmap modules exist.

## Inspect the registry

```bash
reconforge modules list
reconforge modules list --maturity experimental
reconforge modules list --format json
reconforge modules show reconciliation.core
reconforge modules show inventory.core
reconforge modules show studio.modern --format json
reconforge modules validate
```

`modules validate` checks unique IDs, dependency references, dependency cycles, incompatibility references, and migration versions. Inspection never activates a module.

The experimental `inventory.core` entry currently declares migrations 9 through 12: the exact movement ledger, governed count/reorder controls, a bounded FIFO valuation/Finance Core Draft bridge, and exact whole-valuation correction through a separately Posted compensating movement. Reorder remains advisory; valuation and reversal approval never validate Finance Core entries; the registry does not advertise Purchasing, partial/chained reversal, AVCO, landed cost, or ERP writeback as implemented.

The experimental `retail.settlement` entry is an implemented, non-posting
artifact slice for exported POS batches and processor settlements. It exposes
exact refunds/fees/chargebacks, unmatched and ambiguous outcomes, and a
digest-bound report through the local CLI/library, authenticated API, and the
read-only English/Arabic modern Studio projection. Local SQLite and the
explicit PostgreSQL server profile persist replay-verified, workspace-scoped
evidence; the server path refuses silent SQLite fallback. It is not a live
processor connector, a payment/fraud product, an ERP write-back path, or a
complete retail module.

The experimental `bank.cash-reconciliation` entry is an implemented, non-posting
artifact slice for a local CAMT.053 statement and ledger export. It exposes
reference, exact amount, booking-date window, ambiguity, duplicate, unmatched,
and digest verification outcomes through the local CLI/library and a read-only
English/Arabic modern Studio projection. It is not a live bank connector,
payment initiation path, ERP write-back path, or statutory posting engine.

The experimental `manufacturing.cost-control` entry is an implemented,
non-posting artifact slice for local production-order, material-issue,
completion, and scrap exports. It exposes exact material/completion cost
variances, planned-versus-completed quantities, scrap limits, unknown-order
lineage, and digest-bound reports through the local CLI/library and a read-only
English/Arabic modern Studio projection. It is not a statutory valuation engine,
ERP connector, inventory/WIP/GL posting path, or complete manufacturing module.

The experimental `professional.invoice-payment` entry is an implemented,
non-posting artifact slice for local professional-service invoice and payment
exports. It exposes exact client, amount, due-date, ambiguity, unmatched, and
unapplied-cash decisions through the local CLI/library and a read-only
English/Arabic modern Studio projection. It is not a billing connector,
receivables-allocation engine, revenue-recognition system, authenticated live
API, or ERP write-back path.

## Maturity and capability are separate

| Field | Allowed values | Meaning |
| --- | --- | --- |
| `maturity` | `stable`, `beta`, `experimental` | Compatibility confidence for an existing runtime entry |
| `capability_status` | `implemented`, `foundation` | Whether the described workflow is usable end to end or is a bounded foundation |

`planned` is intentionally not a valid runtime maturity. Planned work belongs in the product backlog, not in machine-readable runtime discovery.

## Required metadata

Every registered module declares:

- stable ID, semantic version, display name, maturity, and capability status;
- local-first/external-call posture and optional loopback requirement;
- default-enabled state, dependencies, and incompatibilities;
- existing RBAC permissions and database migration versions;
- domain-event names and exposed interfaces;
- import/export contract names and data classifications;
- operator-controlled retention and activation notes;
- repository-relative test evidence.

The published JSON contract is `docs/schemas/module_registry.schema.json`.

## Current boundaries

- Entries describe code shipped in this checkout only. They do not enumerate roadmap-only ERP modules.
- `default_enabled` is descriptive in this slice; there is no mutating module activation command.
- The export-plugin entry covers built-in local export adapters only. It does not imply direct ERP connectivity or third-party code execution.
- Permissions must exist in the migrated local RBAC seed before they may be declared.
- Test-evidence paths must be bounded repository-relative paths under `tests/` or `apps/web/`.

## Adding an entry

1. Implement a bounded working slice with honest maturity and capability labels.
2. Add its descriptor in `reconforge/modules/registry.py`.
3. Reference only existing dependencies, migrations, permissions, contracts, and test files.
4. Add validation and CLI coverage.
5. Update architecture and product documentation without broadening product claims.
6. Run the full Python quality and security gates.
