# ReconForge Studio Web

`apps/web` is the experimental React/Vite/TypeScript client for ReconForge Studio. It is an additive preview, not a replacement for the current server-rendered `reconforge studio` workspace.

The demonstration pages accept versioned synthetic contracts, including `studio-overview.json`, `studio-exceptions.json`, `studio-evidence.json`, `studio-inventory.json`, and `studio-retail-settlement.json`. Separate live pages use the same-origin authenticated API. `/receivables` supports the bounded invoice workflow documented below; it does not claim a complete ERP or inventory/GL posting cycle.

## Generate local demo data

From the repository root:

```bash
reconforge demo showcase --output output/showcase/enterprise_demo --studio-output apps/web/public/demo/studio-overview.json
```

One bridge command writes the overview, exception queue, evidence registry, and inventory control contract beside one another. It validates the ReconForge synthetic marker, bounds JSON file and record sizes, rejects invalid scalar/metric/checksum/exact-quantity/exact-value records and inconsistent FIFO/reversal/Finance Draft references, and projects allowlisted fields from known demo reports. Valid older packages without the optional inventory sample receive an empty inventory contract. The browser validates nested contract values again before rendering. Published schemas live under `docs/schemas/studio_*.schema.json`.

## Develop and verify

```bash
npm --prefix apps/web install
npm --prefix apps/web run dev
npm --prefix apps/web run typecheck
npm --prefix apps/web run test:run
npm --prefix apps/web run build
npm --prefix apps/web run e2e
```

The Playwright web-server port defaults to `4173`. If that port is reserved by
the host or CI runner, set `RECONFORGE_WEB_PORT` to an available loopback port;
the test base URL and Vite server command use the same value. Live browser
session and HTTPS production-bundle scenarios remain explicit opt-ins through
their documented `RECONFORGE_LIVE_*` variables.

Playwright screenshot tests write real UI captures to `docs/assets/screenshots/`.

## Current boundary

- Implemented here: responsive shell, executive decision brief, close-readiness signal, guided control story, control-domain and entity health, native exception queue, native evidence binder, native inventory controls with on-hand/movement/count/reorder/FIFO-valuation/reversal/layer views, a read-only retail settlement evidence view with exact decimal strings, status filtering, variance reasons, and replay digests, history-based routes, search/filter controls, command palette, current-Studio handoff links, notification/quick/profile panels, theme and density preferences, accessibility controls, English/Arabic direction support, loading/empty/error states, component tests, and screenshot tests.
- Existing product behavior remains in the Python CLI, local API, generated reports, and current Studio. The retail view is a projection of a synthetic report and does not create a second matching or persistence engine.
- Close, reconciliation, import, reports, control-pack, developer, and WIP navigation opens the current local Studio on its default `127.0.0.1:8601` address. Set `VITE_CURRENT_STUDIO_URL` when a different local origin is required.
- The exception, evidence, inventory, and retail demonstration pages expose bounded synthetic metadata. They cannot validate Finance Core entries, settle payments, or write to an ERP. Live session/administration and the bounded receivables page are separate authenticated surfaces; their presence does not establish production deployment readiness.

## Live receivables: draft, submit, independent approval

Serve the production build through the configured PostgreSQL API HTTPS origin,
then open `/receivables`. Sign in with an existing human account, select a
workspace returned by `/api/v1/auth/me`, and select an existing active customer.
The page uses the application's shared, memory-only session state, HttpOnly
cookie, tenant/workspace headers and CSRF proof. It does not persist financial
drafts, passwords or session proofs in browser storage.

An authorized preparer can enter one invoice line, quantity, unit price, line
tax, invoice date and due date, save the Draft, and submit its returned version.
An independently authenticated approver can review the server-returned lines,
creator, currency, total, outstanding balance and version, then explicitly
confirm approval. The UI derives actions from current `/auth/me` permissions;
the server remains authoritative for authorization, segregation of duties,
version, credit and currency checks. No credit override is available here.

Money inputs are explicitly **integer minor units**, with their currency code.
There is no implied two-decimal formatting. Arithmetic uses text and `BigInt`,
HALF_UP line rounding, and a checked conversion only at the legacy JSON integer
boundary. Each received integer and transmitted amount must be within
`0..9007199254740991`; subtotal and total are checked too. Quantities contain at
most 12 digits in total, keeping the coefficient/price product below 28 digits
within the existing AR adapter's precision. Larger values require a future
exact textual API contract; unsafe responses fail closed. For example, quantity
`1.25`, unit price `1001`, and tax `125` produce subtotal `1251` and total `1376`
minor units, without binary floating-point multiplication.

Customer and invoice lists have explicit 25-record pagination. A tenant,
identity or workspace switch discards private records, forms and pending UI
results; late responses cannot repopulate a different scope. Ordinary validation
errors preserve input. An uncertain draft response retains its exact request
and idempotency key for an explicit retry; the UI never silently changes that
payload or automatically retries a mutation. Uncertain submit/approval outcomes
reload records and require another review. Session expiry requires sign-in and
does not replay a financial operation.

New customer creation is deliberately unavailable in this page: the current
`POST /api/v1/receivables/customers` contract is an upsert without an expected
version. An existence check in React cannot make it create-only. Customer setup
remains an explicit administrative API/CLI operation until an atomic create-only
contract exists. Receipt entry/allocation, grouped aging, inventory effects and
GL posting are outside this first UI slice.

Existing backend next operations, performed explicitly with the appropriate
authenticated scope, are:

1. Customer setup: `POST /api/v1/receivables/customers` with `customer_code`,
   `name`, `currency_code`, `credit_limit_minor`, and `workspace`. This updates
   an existing matching code; it is not a create-only command.
2. After invoice approval, record and allocate a receipt using
   `POST /api/v1/receivables/receipts` with `receipt_number`, `customer_code`,
   `receipt_date`, `currency_code`, `amount_minor`, `workspace`, a stable
   `idempotency_key`, and `allocations: [{"invoice_id": "<approved-id>",
   "amount_minor": 1376}]`. The receipt currency/customer must match the invoice.
3. Allocate an existing receipt with
   `POST /api/v1/receivables/receipts/{receipt_id}/allocate` and
   `{"invoice_id":"<approved-id>","amount_minor":1376,"expected_version":1}`,
   replacing the version with the actual latest returned receipt version.

The opt-in Playwright scenario `e2e/receivables-live.spec.ts` requires
`RECONFORGE_AR_UI_BASE_URL`, `RECONFORGE_AR_UI_TENANT`,
`RECONFORGE_AR_UI_WORKSPACE`, and `RECONFORGE_AR_UI_PASSWORD` for a separately
provisioned synthetic HTTPS/PostgreSQL fixture with maker/checker users and
customer `CUS-UI-001`. It verifies real cookie login, exact persisted responses,
submission, independent approval, rejected self-approval/CSRF/foreign scope,
and English/Arabic accessibility. It must not target customer or production data.
