# Local REST API Foundation

ReconForge includes a local/self-hosted REST API foundation for DB-backed workflows.

This API is local-first. The default profile reads and writes local SQLite. An explicit server-auth profile can use PostgreSQL for tenant-scoped identity and sessions while legacy domain routes remain on required database-per-tenant SQLite storage. This does not add SaaS behavior, cloud upload, hosted storage, telemetry, direct ERP connectors, public internet deployment guidance, production hardening claims, SOC/ISO/SOX compliance, SSO, SCIM, OAuth, SAML, legal sign-off, audit opinions, or digital signatures.

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

## Optional database-per-tenant mode

For a bounded self-hosted deployment, route each tenant to an already-migrated
SQLite database under one directory:

```bash
reconforge api serve --tenant-db-root output/tenants --host 127.0.0.1 --port 8765
```

Every database-backed request must then include `X-ReconForge-Tenant: tenant-a`.
Tenant IDs are deliberately restricted and resolve only to `<tenant-id>.db` beneath
the configured root. Missing or invalid scope is rejected. This mode is a
database-per-tenant SQLite boundary; it is not shared-schema PostgreSQL/RLS,
centralized identity, or hosted production readiness.

The CLI exposes the explicit PostgreSQL server-auth profile through environment
configuration:

```bash
$env:RECONFORGE_POSTGRES_DSN = "postgresql://reconforge_app@db.example/reconforge"
reconforge api serve --tenant-db-root output/tenants
```

Use `--postgres-no-tls` or `--redis-no-tls` only for disposable local services.
The PostgreSQL profile refuses to start without `--tenant-db-root` because
legacy domain routes still require database-per-tenant SQLite isolation.

## Optional Redis coordination

The Python app factory can opt into a tenant-scoped Redis rate-limit backend:

```python
from reconforge.api import create_api_app

app = create_api_app(
    "output/reconforge.db",
    redis_url="rediss://redis.example/reconforge",
)
```

Install the optional server dependencies with
`pip install "reconforge-erp[server]"`. TLS is required by default; disabling
it is intended only for a local disposable Redis service. When configured, failed
login counters use Redis atomic increments instead of process-local memory and
Redis outages fail closed with a structured service-unavailable response. The
Redis session/revocation and distributed-lock primitives are implemented in
`reconforge.infrastructure.redis`, but existing SQLite session persistence is
not silently replaced until a server deployment profile migrates the full auth
lifecycle.

## Authentication

The default API uses local users stored in the ReconForge SQLite database. Login creates a random local session token and stores only its hash. Disabled users cannot authenticate. Tokens can expire or be revoked.

### PostgreSQL server-auth profile

The app factory supports an explicit server profile:

```python
from reconforge.api import create_api_app

app = create_api_app(
    "output/unused.db",
    tenant_db_root="output/tenants",
    postgres_dsn="postgresql://reconforge_app@db.example/reconforge",
)
```

This profile requires `X-ReconForge-Tenant` on authenticated requests and uses
PostgreSQL/RLS for password verification, RBAC, bearer-session hashing, expiry,
and revocation. The verified principal is propagated into current API/domain
authorization and audit calls. `tenant_db_root` is mandatory because the
remaining legacy domain routes still use tenant-local SQLite; this is a bounded
transition profile, not full hosted PostgreSQL persistence. Use TLS verification
and a non-superuser, non-`BYPASSRLS` database role in deployment.

Implemented endpoints:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/federation/challenge` (only with bounded federation configuration)
- `POST /api/v1/auth/federated-login` (requires the server-issued challenge)
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Federation is disabled by default. To enable the bounded OIDC/SAML verification
profile, install the `federation` extra and pass a versioned JSON file containing
operator-owned public JWKS or public IdP certificates:

```powershell
$env:RECONFORGE_POSTGRES_DSN = "postgresql://reconforge_app@db.example/reconforge"
$env:RECONFORGE_FEDERATION_CONFIG = "C:\secure-config\federation.json"
reconforge api serve --tenant-db-root output/tenants
```

The challenge endpoint returns an OIDC `nonce` or SAML `request_id`; the login
request must return that correlation plus `challenge_id`. The server stores only
their hashes and consumes them once. This direct assertion-verification profile
does not itself implement authorization-code exchange, dynamic discovery,
IdP-initiated SAML, SCIM, provider single logout, or hosted IdP certification.
Authenticated SCIM and WebAuthn MFA are separate explicitly configured server
boundaries documented below.

In this profile, the following Finance Core operations are also backed by the
tenant-scoped PostgreSQL ledger boundary:

- `GET /api/v1/finance-core/summary`
- `GET, POST /api/v1/finance-core/accounts`
- `GET /api/v1/finance-core/entries`
- `GET /api/v1/finance-core/entries/{entry_id}`
- `GET /api/v1/finance-core/trial-balance`

Server-mode entry creation posts an immutable balanced entry atomically. It
requires `organization_code` and `currency_code` (or an organization base
currency), and currently accepts no entity, fiscal-period, journal, or analytic
dimension fields. Charts, dimensions, journals, full snapshots,
legal-entity-scoped trial balances, draft validation, and voiding are explicitly
unavailable in server mode and return HTTP `501`; organization/fiscal-period
trial balance is supported without a local fallback.

Do not put passwords or tokens in docs, shell history, logs, generated reports, fixtures, or control packs.

The following master-data operations are backed by the tenant-scoped
PostgreSQL master-data boundary:

- `GET /api/v1/master-data/summary`
- `GET /api/v1/master-data/snapshot`
- `GET, POST /api/v1/master-data/currencies`
- `GET, POST /api/v1/master-data/organizations`
- `GET, POST /api/v1/master-data/entities`
- `GET, POST /api/v1/master-data/branches`
- `GET, POST /api/v1/master-data/periods`
- `POST /api/v1/master-data/periods/{period_id}/status`

Master-data writes append audit-chain and transactional-outbox evidence in the
same PostgreSQL transaction as the mutation. Fiscal-period list, create, and
status operations use the tenant-scoped PostgreSQL fiscal-period table and
remain metadata-only: they do not lock source-ERP postings. They never fall
back to tenant-local SQLite.

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

In the explicit PostgreSQL server profile these endpoints read and verify the
tenant-scoped PostgreSQL audit chain produced by the supported server
boundaries. They never fall back to the legacy SQLite audit ledger. The local
profile retains the SQLite audit event schema and verification behavior.

PostgreSQL audit administration:

- `GET /api/v1/admin/audit/events`
- `GET /api/v1/admin/audit/verify`

These server-only routes require human `audit.read` or `audit.verify`, current
privileged assurance, and (for browse) an operator-owned cursor signing key.
They page a redacted union of the independent `domain` and `ledger_control`
chains. They never return raw actor/object identifiers, reasons, request IDs,
or metadata, and they do not claim a global cross-source hash chain. See the
audit-administration runbook for the precise incident boundary.

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

In PostgreSQL server mode, close periods and tasks use the tenant-scoped
PostgreSQL close-control boundary. `POST /close/periods` requires an existing
`fiscal_period_id` and `organization_code`; it creates five deterministic
starter tasks. Task completion is blocked by incomplete dependencies, approval
and locking require 100% readiness, and reopening requires a reason. These
states coordinate ReconForge close work only; they do not lock source-ERP
postings. Close mutations append PostgreSQL audit-chain and outbox evidence in
the same transaction and never fall back to SQLite.

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

Accounts Payable three-way-match foundation:

- `POST /api/v1/payables/suppliers`
- `GET /api/v1/payables/suppliers`
- `POST /api/v1/payables/purchase-orders`
- `POST /api/v1/payables/purchase-orders/{purchase_order_id}/submit`
- `POST /api/v1/payables/purchase-orders/{purchase_order_id}/approve`
- `POST /api/v1/payables/receipts`
- `POST /api/v1/payables/invoices`
- `GET /api/v1/payables/invoices`
- `POST /api/v1/payables/invoices/{invoice_id}/submit`
- `POST /api/v1/payables/invoices/{invoice_id}/match`
- `POST /api/v1/payables/invoices/{invoice_id}/approve`

AP money fields use integer minor units and quantities use canonical decimal text. The bounded slice requires invoice lines to reference PO lines, rejects over-receipts, records deterministic match variances and exception-queue evidence, and uses idempotency keys and row-version checks where supplied. Approval is local workflow evidence only: these routes do not post a statutory payable, calculate statutory tax or withholding, issue payments, or write to a source ERP. See [Accounts Payable guide](payables.md).

Accounts Receivable and credit-control foundation:

- `POST /api/v1/receivables/customers`
- `GET /api/v1/receivables/customers`
- `POST /api/v1/receivables/invoices`
- `GET /api/v1/receivables/invoices`
- `POST /api/v1/receivables/invoices/{invoice_id}/submit`
- `POST /api/v1/receivables/invoices/{invoice_id}/approve`
- `POST /api/v1/receivables/receipts`
- `POST /api/v1/receivables/receipts/{receipt_id}/allocate`
- `GET /api/v1/receivables/credit-exposure/{customer_code}`
- `GET /api/v1/receivables/aging?as_of_date=YYYY-MM-DD`

AR values use integer minor units and canonical decimal quantities. Approval checks customer status, credit hold, and exposure against the configured credit limit. A hold or limit breach requires `receivables.credit_override` and a persisted reason; known-user creator/approver separation is enforced. Receipts may remain explicitly unapplied and allocations cannot exceed receipt or invoice outstanding balances. This slice does not post statutory revenue/receivables entries, calculate tax, execute payments, run dunning, or write to a source ERP. See [Accounts Receivable guide](receivables.md).

PostgreSQL reconciliation execution boundary:

- `POST /api/v1/reconciliations/runs` — atomically submit a bounded run manifest and canonical left/right inputs; requires `reconciliation.manage` or `match.run` and supports the `Idempotency-Key` header.
- `GET /api/v1/reconciliations/runs`
- `GET /api/v1/reconciliations/runs/{run_id}`
- `GET /api/v1/reconciliations/runs/{run_id}/inputs`
- `GET /api/v1/reconciliations/runs/{run_id}/results`
- `GET /api/v1/reconciliations/runs/{run_id}/exceptions`
- `POST /api/v1/reconciliations/runs/{run_id}/cancel`
- `POST /api/v1/reconciliations/runs/{run_id}/requeue`

Submission is capped at 5,000 inputs and 20 MB per request. The worker adapter is deterministic and schema-only in-memory SQLite. Rules may opt into hard-key partitioning with `partition_fields` and `partition_max_records`; the in-process `PostgresReconciliationScheduler` can run multiple leased worker slots. Partitioned adapter workers stream one tenant-scoped PostgreSQL cursor partition at a time, commit output and a deterministic checkpoint hash atomically, and explicit requeue resumes after committed partitions. Global relation-native assignment and million-row hosted processing remain open.

In the explicit PostgreSQL server profile, evidence metadata is exposed through `GET /api/v1/evidence`, `GET /api/v1/evidence/records/{id}`, `GET /api/v1/evidence/coverage`, and governed metadata/link/requirement/verification writes under `/api/v1/evidence/`. These routes never accept arbitrary artifact bytes or expose download URLs; a trusted storage worker must upload and checksum content before registering the immutable provider reference.

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
- API coverage for journals, intercompany, controls, and matching remains primarily CLI/DB service first in this slice. Local evidence registration remains available through the CLI; the explicit PostgreSQL server profile now exposes tenant-scoped evidence metadata, links, requirements, coverage, and trusted checksum-verification records, but not arbitrary object upload/download URLs.
- Transactional outbox inspection/replay is available locally with `reconforge outbox list` and `reconforge outbox requeue`; `reconforge.workers.outbox.OutboxWorker` provides bounded fresh-connection polling, while external publishing still requires an injected transport and deployment-managed worker.
- The PostgreSQL server profile additionally provides `reconforge.infrastructure.postgres_outbox.PostgresOutboxRepository` and `reconforge.workers.postgres_outbox.PostgresOutboxWorker` for tenant-scoped claim, lease, acknowledgement, retry, dead-letter, and replay delivery. The worker publishes outside the database transaction and acknowledges by `(tenant_id, event_id, worker_id)`; publishers must treat the event ID as an idempotency key because a crash after publishing can require a safe duplicate retry. No public outbox API or external transport is claimed.
- `reconforge.infrastructure.postgres_reconciliation.PostgresReconciliationRepository` is a tenant-scoped persistence contract for matcher workers: it records canonical inputs, deterministic results, explainable exceptions, completion hashes, cardinality invariants, and idempotent partition checkpoints. In the authenticated PostgreSQL server profile, `POST /api/v1/reconciliations/runs` atomically accepts a bounded run manifest and canonical left/right inputs with `Idempotency-Key`, while read routes expose paginated run metadata and child input/result/exception records and manage routes request cancellation or explicit retry. `reconforge.workers.postgres_reconciliation.PostgresReconciliationWorker` provides durable claims, leases, heartbeats, cooperative cancellation, retryable failure, and atomic persistence for the explicit `LocalDeterministicMatcherAdapter`, which uses only a schema-only in-memory SQLite dependency and never writes hosted financial data there. Hard-key partitioning, PostgreSQL server-cursor input streaming, checkpoint resume, and the multi-worker scheduler are implemented; global relation-native assignment and million-row hosted execution are not claimed.
- This is not production enterprise identity, public cloud readiness, SOC/ISO/SOX compliance, legal sign-off, audit opinion, or digital signature support.

## SCIM 2.0 provisioning (PostgreSQL profile)

The bounded SCIM surface is `/scim/v2`. It is disabled unless the API is started with the explicit PostgreSQL server profile. Every request requires `Authorization: Bearer <opaque-token>` and `X-ReconForge-Tenant`; discovery is authenticated too. The routing tenant is not authority by itself: the token hash must authenticate inside that tenant's forced-RLS transaction.

Supported resources are Users and role-free Groups. Discovery, create, exact equality filters, pagination, get, conditional PUT/PATCH, User deactivation, and Group deletion are supported. Mutations require the current weak ETag in `If-Match`. Bulk, sorting, arbitrary attributes/schemas/filters/PATCH paths, password provisioning, and Group-to-RBAC mapping are not supported.

Operators create credentials with `reconforge scim credential-issue`, replace them atomically with `credential-rotate`, and invalidate them with `credential-revoke`. Prefer `RECONFORGE_POSTGRES_DSN` over a command-line DSN. The issue/rotate response contains the bearer value exactly once; only its SHA-256 digest is persisted. The current `oauthbearertoken` discovery label describes bearer transport compatibility and does not claim an OAuth authorization server.

## Service-account authentication (PostgreSQL profile)

Service credentials use the reserved `rfa_` bearer prefix and authenticate only
inside the selected tenant's forced-RLS transaction. They become typed machine
principals, never user sessions: user roles are not loaded and only the active
account's current direct permissions participate in authorization. `GET
/api/v1/auth/me` exposes `principal_type: service_account`, an empty role list,
and the bounded direct permission set. `POST /api/v1/auth/logout` revokes the
presented service credential.

The central policy boundary rejects all configured human-governed permissions
and every permission ending in `.approve`, `.review`, or `.complete` for a
service principal. Dynamic workflow transitions also require a human principal.
This contract does not provide workload identity federation, privileged human
step-up, emergency access, hosted operation, or Enterprise readiness.

## Privileged human session step-up (PostgreSQL profile)

Selected high-risk permissions require recent human reauthentication in
addition to the existing role grant. A denied request returns the structured
`step_up_required` code. The authenticated human may call `POST
/api/v1/auth/step-up` with a closed JSON body containing `password`; success
returns `method: password_reauthentication` and the expiry timestamp. `GET
/api/v1/auth/me` reports the current step-up state without credential material.

The assertion is bound to the current tenant, user, and bearer session and is
valid for at most ten minutes. Logout/session revocation or session expiry
invalidates it. This route is unavailable in Community/SQLite mode and rejects
service accounts. It is password reauthentication, not MFA, and currently does
not provide external-IdP ACR/AMR validation, phishing resistance, emergency
access, or independent assurance.

## Same-origin browser administration session

`POST /api/v1/auth/browser/login` accepts the same closed username/password
payload as bearer login but returns only `csrf_token` and `expires_at`. It sets
the bearer session only as the host-only `__Host-reconforge_session` cookie
with `HttpOnly`, `Secure`, `Path=/`, and `SameSite=Strict`. It never exposes an
`access_token` in the browser-login response.

Safe cookie-authenticated requests need no extra header. Every unsafe request
using that cookie must send the current `X-ReconForge-CSRF` proof from the
browser-login response. The proof is bound to that exact session; a proof from
another session fails. The explicit `Authorization: Bearer` API/CLI contract
is unchanged and takes precedence when both transports are presented. Browser
logout requires the proof, revokes the server session, and clears the cookie.

This is a same-origin HTTPS transport boundary, not a hosted browser UI,
cross-origin credential facility, CSP configuration, accessibility claim, or
complete WebAuthn/step-up experience. See
`docs/operations/browser-administration-sessions.md`.

## Emergency access (PostgreSQL profile)

`/api/v1/auth/emergency-access/requests` exposes a human-only, forced-RLS
lifecycle: self-request and list, independent stepped-up approve/reject,
requester activation from the same stepped-up session, explicit end, and
independent stepped-up review. Authority is limited to a closed five-permission
financial/operational registry and 5–60 minutes. It never grants identity,
role, policy, service-account, or security administration.

Every authorization that depends on an emergency permission appends the exact
permission and externally addressed HTTP path before the operation proceeds.
End or expiry enters `ReviewPending`; it is not silently treated as reviewed.
The surface is unavailable in Community/SQLite and rejects service accounts.
This is a bounded emergency control, not MFA, production PAM, hosted readiness,
or independent assurance.

## WebAuthn MFA (PostgreSQL profile)

Install the optional `mfa` extra and pass `--webauthn-config` (or
`RECONFORGE_WEBAUTHN_CONFIG`) containing the closed v1 RP ID/name/exact-origin
object. Without that explicit configuration all WebAuthn routes remain
unavailable. HTTPS is mandatory outside matching loopback origins.

An authenticated human first performs password step-up, then calls
`POST /api/v1/auth/webauthn/registration/options` and submits the browser result
to `/registration/verify`. Later `/authentication/options` and
`/authentication/verify` complete user-verified WebAuthn step-up. Challenges
last five minutes, are bound to the current tenant/user/session/ceremony, and
are consumed once before verification. Credential private keys never reach the
server.

When configured, the closed privileged permission registry requires the
`webauthn_user_verified` method; password-only assurance returns
`mfa_required`. This evidence does not cover every browser/authenticator,
recovery ceremony, attestation policy, hosted deployment, or independent review.

## Administration security overview (PostgreSQL profile)

`GET /api/v1/admin/security/overview` requires a human principal with
`security.center.read` and current privileged assurance. With WebAuthn enabled,
user-verified WebAuthn is required. Service accounts are denied by Application,
central policy, and migration 0049's database constraint.

The closed v1 response reports count-only identity, session, integration,
policy, evidence-retention/verification, and audit observations. It contains a
tenant-scope digest, whole-second `as_of`, deterministic snapshot digest, and
bounded attention codes. It does not expose identity rows, credentials,
destinations, source financial data, or free-form audit content. Audit-chain
verification remains a separate `audit.verify` operation. This read-only
surface is not a security assessment, certification, or complete
administration center.

## Identity and session administration (PostgreSQL profile)

The authoritative server routes are:

- `GET /api/v1/admin/identity/users`
- `POST /api/v1/admin/identity/users/{user_id}/status`
- `GET /api/v1/admin/identity/sessions`
- `POST /api/v1/admin/identity/sessions/{session_id}/revoke`

Every route requires a human principal with `users.manage` and current
privileged assurance. With WebAuthn enabled, user-verified WebAuthn is
required. List routes use 1–200 item signed cursor pages; the cursor is bound
to tenant, resource, filter, sort, and direction.

User status and session revocation requests require the exact positive
`expected_lifecycle_version`. A stale version returns
`identity_lifecycle_version_conflict`. User disable revokes every current
session atomically; enabling does not resurrect old sessions. Self-disable and
disabling the last active identity administrator are refused.

Session reasons are closed to `access_change`, `administrative_cleanup`,
`security_response`, and `user_request`. Responses include only presence flags
for recorded client IP/user agent and exclude credentials, tokens, token
hashes, raw IP/user-agent values, password fields, and email.

In the PostgreSQL profile, historical `/api/v1/users` endpoints return
`local_identity_surface_disabled` because they address the Community SQLite
identity store. Those endpoints remain backward compatible in local mode.

## Role and access-policy administration (PostgreSQL profile)

The authoritative server routes are:

- `GET /api/v1/admin/access/permissions`
- `GET /api/v1/admin/access/roles`
- `POST /api/v1/admin/access/roles`
- `PATCH /api/v1/admin/access/roles/{role_id}`
- `PUT /api/v1/admin/access/roles/{role_id}/permissions`
- `PUT /api/v1/admin/access/users/{user_id}/roles`
- `POST /api/v1/admin/access/policy-analysis`

The policy-analysis route is read-only. It requires the human-governed
`security.policy.manage` permission and an independent `approved_by` plus
prior `approved_at` timestamp. It analyzes the active PostgreSQL RBAC and
enabled service-account snapshot under tenant RLS; it does not mutate policy,
invalidate distributed caches, or call an external identity provider.

Every route requires a human `roles.manage` principal and current privileged
assurance. Role list cursors are signed and bound to the tenant, retirement
filter, sort direction, and tie-breaker. Mutations use optimistic lifecycle
versions and exact permission/role sets. Unknown permissions are rejected;
the permission registry is read-only over HTTP.

Role names are immutable. Retirement revokes its active user assignments and
all affected live sessions; reactivation does not resurrect assignments.
Changing a role policy or a user's exact role set also invalidates affected
sessions. The final effective active `roles.manage` authority cannot be
removed. Responses omit credentials, tokens, hashes, email, network address,
and user-agent values.

In the PostgreSQL profile, both historical `/api/v1/roles` reads return
`local_identity_surface_disabled` before opening SQLite. They remain backward
compatible in Community/local mode. See
`docs/operations/access-administration.md` for recovery and claim limits.

## Integration and retention administration (PostgreSQL profile)

The authoritative server routes are:

- `GET /api/v1/admin/security/integrations`
- `POST /api/v1/admin/security/integrations/{kind}/{integration_id}/disable`
- `GET|POST /api/v1/admin/security/retention-policies`
- `PATCH /api/v1/admin/security/retention-policies/{policy_id}`
- `POST /api/v1/admin/security/retention-policies/{policy_id}/evidence/{evidence_id}`

Every route requires a human `security.policy.manage` principal and current
privileged assurance. Signed cursors bind tenant, resource, inactive/retired
filter, ordering, and tie-breaker. Integration kinds are limited to real
federation links, SCIM credentials, service accounts, and notification routes;
no shadow connector registry is created.

Disable requests carry the current state digest and a closed reason code. The
native runtime transition, credential revocation where applicable, native
lifecycle evidence, and bounded domain-audit event commit atomically. Responses
exclude tokens and hashes, external-subject hashes, destinations, secret
references, raw actor identifiers, email, IP, and user-agent values.

Retention policies have immutable names, optimistic lifecycle versions, closed
classifications/reasons, and retirement instead of deletion. Applying one
creates append-only assignment evidence and can extend but never shorten the
evidence retention floor. Exact replay is idempotent. This is database metadata
governance only; it does not prove legal validity or propagate WORM locks to
object stores, backups, replicas, or exports. See
`docs/operations/security-governance.md` for incident and recovery procedures.
