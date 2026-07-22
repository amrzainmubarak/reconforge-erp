# Local REST API Foundation

ReconForge includes a local/self-hosted REST API foundation for DB-backed workflows.

This API is local-first. It reads and writes the local SQLite database selected by the user and does not add SaaS behavior, cloud upload, hosted storage, telemetry, direct ERP connectors, public internet deployment guidance, production hardening claims, SOC/ISO/SOX compliance, SSO, SCIM, OAuth, SAML, legal sign-off, audit opinions, or digital signatures.

## Starting The API

Initialize and migrate the local database first:

```bash
reconforge db init --db output/reconforge.db
```

Start the API:

```bash
reconforge api serve --db output/reconforge.db --host 127.0.0.1 --port 8765
```

The default bind host is `127.0.0.1`. Binding to `0.0.0.0` prints a warning because this is not a public internet deployment mode.

## Authentication

The API uses local users stored in the ReconForge SQLite database. Login creates a random local session token and stores only its hash. Disabled users cannot authenticate. Tokens can expire or be revoked.

Implemented endpoints:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Do not put passwords or tokens in docs, shell history, logs, generated reports, fixtures, or control packs.

## Endpoints

Unauthenticated:

- `GET /api/v1/health`
- `GET /api/v1/version`
- `POST /api/v1/auth/login`

Authenticated local users and roles:

- `GET /api/v1/users`
- `POST /api/v1/users`
- `PATCH /api/v1/users/{username}`
- `POST /api/v1/users/{username}/disable`
- `POST /api/v1/users/{username}/roles`
- `DELETE /api/v1/users/{username}/roles/{role_name}`
- `GET /api/v1/users/{username}/permissions`
- `GET /api/v1/roles`
- `GET /api/v1/roles/{role_name}/permissions`

Audit:

- `GET /api/v1/audit/events`
- `GET /api/v1/audit/verify`

Workflow state machine foundation:

- `GET /api/v1/workflow/transitions?object_type=reconciliation`
- `POST /api/v1/workflow/objects`
- `GET /api/v1/workflow/objects/{object_type}/{object_id}`
- `POST /api/v1/workflow/objects/{object_type}/{object_id}/transition`
- `GET /api/v1/workflow/objects/{object_type}/{object_id}/history`

Account reconciliations:

- `GET /api/v1/accounts/reconciliations`
- `POST /api/v1/accounts/reconciliations`
- `GET /api/v1/accounts/reconciliations/{id}`
- `POST /api/v1/accounts/reconciliations/{id}/prepare`
- `POST /api/v1/accounts/reconciliations/{id}/submit`
- `POST /api/v1/accounts/reconciliations/{id}/review`
- `POST /api/v1/accounts/reconciliations/{id}/complete`

Close management:

- `GET /api/v1/close/periods`
- `POST /api/v1/close/periods`
- `GET /api/v1/close/tasks`
- `POST /api/v1/close/tasks/{task_id}/status`
- `GET /api/v1/close/periods/{period_id}/readiness`
- `POST /api/v1/close/periods/{period_id}/lock`
- `POST /api/v1/close/periods/{period_id}/reopen`

Exceptions and metrics:

- `GET /api/v1/exceptions`
- `POST /api/v1/exceptions/{exception_id}/assign`
- `POST /api/v1/exceptions/{exception_id}/status`
- `GET /api/v1/metrics/dashboard`
- `GET /api/v1/metrics/lineage`

Organization and fiscal master data:

- `GET /api/v1/master-data/summary`
- `GET /api/v1/master-data/snapshot`
- `GET|POST /api/v1/master-data/currencies`
- `GET|POST /api/v1/master-data/organizations`
- `GET|POST /api/v1/master-data/entities`
- `GET|POST /api/v1/master-data/branches`
- `GET|POST /api/v1/master-data/periods`
- `POST /api/v1/master-data/periods/{period_id}/status`

Master-data reads require `master_data.read` or `master_data.manage`; mutations require `master_data.manage`. Currency rows are references only, and fiscal-period status does not lock source-ERP postings.
Master-data list routes use `limit` and `offset` query parameters, default to 500 rows, cap a page at 1,000 rows, and include applied pagination metadata in the response.

Finance core control ledger:

- `GET /api/v1/finance-core/summary`
- `GET /api/v1/finance-core/snapshot`
- `GET|POST /api/v1/finance-core/charts`
- `GET|POST /api/v1/finance-core/accounts`
- `GET|POST /api/v1/finance-core/dimensions`
- `GET|POST /api/v1/finance-core/dimension-values`
- `GET|POST /api/v1/finance-core/journals`
- `GET|POST /api/v1/finance-core/entries`
- `GET /api/v1/finance-core/entries/{entry_id}`
- `POST /api/v1/finance-core/entries/{entry_id}/validate`
- `POST /api/v1/finance-core/entries/{entry_id}/void`
- `GET /api/v1/finance-core/trial-balance`

Finance-core reads require `finance_core.read`, draft/master mutations require `finance_core.manage`, and validation/void actions require `finance_core.validate`. List pages default to 500 and cap at 1,000 rows. These routes manage a local control ledger only; they do not post to a source ERP or constitute statutory financial statements.

Inventory core movement ledger:

- `GET /api/v1/inventory/summary`
- `GET /api/v1/inventory/snapshot`
- `GET|POST /api/v1/inventory/units`
- `GET|POST /api/v1/inventory/items`
- `GET|POST /api/v1/inventory/warehouses`
- `GET|POST /api/v1/inventory/locations`
- `GET|POST /api/v1/inventory/lots`
- `GET|POST /api/v1/inventory/movements`
- `GET /api/v1/inventory/movements/{movement_id}`
- `POST /api/v1/inventory/movements/{movement_id}/post`
- `POST /api/v1/inventory/movements/{movement_id}/void`
- `GET /api/v1/inventory/on-hand`
- `GET /api/v1/inventory/control-exceptions`

Inventory reads require `inventory.read`, Draft/master mutations require `inventory.manage`, and posting/void actions require `inventory.post`. Known local creators cannot post their own movements. List pages default to 500 and cap at 1,000 rows. `Posted` changes ReconForge's local derived on-hand only; these routes do not reserve, pick, cost, value, account for, or write stock to a source ERP. FIFO valuation uses the separate routes below.

Inventory planning:

- `GET /api/v1/inventory-planning/summary`
- `GET /api/v1/inventory-planning/snapshot`
- `GET|POST /api/v1/inventory-planning/counts`
- `GET /api/v1/inventory-planning/counts/{session_id}`
- `POST /api/v1/inventory-planning/counts/{session_id}/start`
- `POST /api/v1/inventory-planning/counts/{session_id}/lines/{line_id}`
- `POST /api/v1/inventory-planning/counts/{session_id}/submit`
- `POST /api/v1/inventory-planning/counts/{session_id}/approve`
- `POST /api/v1/inventory-planning/counts/{session_id}/cancel`
- `GET|POST /api/v1/inventory-planning/reorder-rules`
- `GET /api/v1/inventory-planning/reorder-signals`

Count preparation uses `inventory.count.manage`; submitted approval/cancellation uses `inventory.count.approve`; rule mutation uses `inventory.reorder.manage`; reads use `inventory.read`. Count approval rejects known-user self-approval and stale Posted balance snapshots. A variance creates only a Draft local adjustment. Reorder signals are deterministic advice and do not create purchasing documents or external calls.

FIFO inventory valuation:

- `GET /api/v1/inventory-valuation/summary`
- `GET /api/v1/inventory-valuation/snapshot`
- `GET|POST /api/v1/inventory-valuation/policies`
- `GET|POST /api/v1/inventory-valuation/documents`
- `GET /api/v1/inventory-valuation/documents/{document_id}`
- `POST /api/v1/inventory-valuation/documents/{document_id}/approve`
- `POST /api/v1/inventory-valuation/documents/{document_id}/cancel`
- `GET /api/v1/inventory-valuation/cost-layers`

Valuation reads accept `inventory.read` or either valuation permission. Policy/document preparation and Draft cancellation require `inventory.valuation.manage`; approval requires `inventory.valuation.approve` and known-user creator/approver separation. Approval writes immutable FIFO evidence and prepares a balanced Finance Core **Draft** atomically. It never validates that entry or writes to a source ERP. Request objects reject unknown fields; lists default to 500 and cap at 1,000 rows.

Exact FIFO valuation reversal:

- `GET /api/v1/inventory-valuation/reversals/summary`
- `GET /api/v1/inventory-valuation/reversals/snapshot`
- `GET|POST /api/v1/inventory-valuation/reversals`
- `GET /api/v1/inventory-valuation/reversals/{reversal_id}`
- `POST /api/v1/inventory-valuation/reversals/{reversal_id}/approve`
- `POST /api/v1/inventory-valuation/reversals/{reversal_id}/cancel`

Reversal reads accept `inventory.read` or either reversal permission. Draft creation/cancellation requires `inventory.valuation.reverse.manage`; approval requires `inventory.valuation.reverse.approve` and known-user creator/approver separation. Creation links an Approved valuation to a separately Posted exact opposite movement. Approval atomically records immutable FIFO `Restore`/`Remove` effects and prepares a debit/credit-swapped Finance Core **Draft**; it deletes no history, validates no entry, and writes to no source ERP.

## Errors

API errors use a structured JSON shape:

```json
{
  "error": {
    "code": "permission_denied",
    "message": "Permission denied.",
    "request_id": "local-request-id"
  }
}
```

Responses must not include raw tracebacks, password hashes, salts, raw persisted tokens, environment variables, or secrets.

## Boundaries

- API authentication is a local session foundation only.
- API routes do not replace Studio auth and do not enable SaaS use.
- Workflow routes operate on the DB-backed workflow state machine only; they do not migrate or enforce identity on legacy JSON workflows.
- API coverage for journals, intercompany, evidence registry, controls, and matching remains primarily CLI/DB service first in this slice.
- This is not production enterprise identity, public cloud readiness, SOC/ISO/SOX compliance, legal sign-off, audit opinion, or digital signature support.
