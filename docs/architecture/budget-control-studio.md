# Governed operational budget Studio

The `/budget-control` workspace exposes the existing registered SQLite52 /
PostgreSQL0102 budget engine. It adds no database schema and retains the existing
exact-money, current-authority, maker-checker, immutable-history and atomic
audit/outbox/command contracts. The navigation registration belongs to the
integration branch. Its supported operations are create, submit, independently
approve, reserve, consume and release an operational appropriation. A source
reference is evidence supplied by the operator; it does not automatically post a
purchase order, payable, cash transaction or general ledger entry.

The browser uses an HTTPS same-origin HttpOnly session cookie and its in-memory
CSRF proof. The current `/auth/me` identity provides permissions and server scope
grants. Canonical scope IDs remain explicit; the selected workspace, organization
and legal entity are sent both as headers and in each exact command/query. The
server verifies hierarchy and grants again. Editing scope immediately removes
loaded balances and commands; a user must explicitly load the new scope. A local
SQLite deployment retains its existing single-file RBAC model. This UI does not
introduce tenant or per-scope grant functionality into local mode.

Draft limits use explicit positive minor-unit strings because their currency
policy has not yet been captured. Server-confirmed records include the retained
currency precision, rounding policy and registry digest. Commitment input uses
that exact retained precision, accepts Arabic and Persian digits, and refuses
excess fractional digits. All amounts and conservation use `BigInt` and textual
serialization. JSON numbers are refused for monetary fields. Unsupported unsafe
JavaScript version integers are refused, never rounded into a different version.

`scoped-command.ts` prepares a frozen route/body with one random command ID.
`budget-control-data.ts` binds its full scope, exact version, reason and amount.
A lost response, a server5xx, or an invalid successful-response contract can
follow a committed transaction. The workspace therefore locks editing and scope
selection and offers only an exact retry. The same command, actor, key and
expected version reach the existing persisted command ledger; a retry can obtain
the retained receipt without a second business effect. A confirmed receipt is
shown separately from a fresh GET of current balances, since an old command
receipt may describe an earlier version. A definitive server refusal requires
current balances to be reloaded before a new command. The server remains the
authority for step-up assurance, amount policies and segregation of duties.

Command recovery lives only in the mounted authenticated browser session. Do not
close the tab or sign out while an outcome is unknown: first retry that exact
command. If the browser is closed, review the retained command/event ledger before
attempting a replacement. Financial bodies, session credentials and receipts are
never persisted in browser storage. Session change unmounts private state and
discards late responses. The event view is bounded to the API's latest100 events
and explicitly reports incomplete history. The existing engine caps an envelope
at1000 commitment events.

## Reproducible populated acceptance

From `apps/web`, build the isolated product-component harness:

```powershell
npm.cmd run typecheck
npm.cmd run test:run -- src/budget-control-data.test.ts src/components/BudgetControlWorkspace.test.tsx
npx.cmd vite build --config e2e/budget-control.vite.config.ts
$env:RECONFORGE_BUDGET_UI_PYTHON = 'F:\reconforge-erp\.venv-baseline-20261008\Scripts\python.exe'
npx.cmd playwright test --config e2e/budget-control.playwright.config.ts
```

The fixture creates a disposable actual SQLite database, registered migrations,
canonical organization/entity/period, and two persisted synthetic identities.
The HTTPS runtime has a short-lived localhost certificate. The browser test
executes actual API routes and database transactions. Its transport fault uses
`route.fetch()` to execute the real reserve command, then drops its acknowledgement;
it never replaces a financial response with a synthetic successful response.
It exercises draft→submit→independent approval, reserve4000→consume1500→release2500,
exact retry, current balance readback, immutable events, CSRF refusal and scope
refusal, page reload, accessibility and mobile Arabic rendering. Evidence is
written to `output/budget-ui/runtime/browser-evidence.json`. The harness tests the
unchanged product component independently of the central application registration;
the integrated `/budget-control` route must additionally pass the lead's gate.
To run that same actual workflow against the normal built Studio, set
`RECONFORGE_BUDGET_UI_WEB_ROOT=dist` and
`RECONFORGE_BUDGET_UI_PATH=/budget-control` after `npm.cmd run build`.

The live acceptance depends on the request-owned SQLite connection worker-handoff
repair in `api.dependencies.get_db`: FastAPI may open, execute and close a single
request's dependency in distinct worker threads. That repair preserves default
thread affinity for CLI/library callers and allocates a separate connection for
each request. The component gate does not claim PostgreSQL browser acceptance,
financial posting integration, capacity, HA/DR, production deployment or compliance.
