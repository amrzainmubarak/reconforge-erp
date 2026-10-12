# Reproduce the synthetic retained-policy browser journey

This run exercises real password/step-up HTTP sessions, PostgreSQL application
role persistence and the built React application. It covers AR subledger data;
it does not execute bank payments, FX conversion or operational GL posting.
ADR0821 and the API/UI acceptance reports define the evidence boundary.

Use the locked Python3.12 server/development dependencies, Node22 dependencies,
Playwright Chromium and an isolated synthetic PostgreSQL16 profile. Supply the
existing `RECONFORGE_TEST_POSTGRES_ADMIN_DSN` and
`RECONFORGE_TEST_POSTGRES_DSN` variables. The administration profile must be able
to create/drop disposable databases; the application role must be nonowner,
without SUPERUSER/BYPASSRLS. `synthetic_cash_runtime` creates a unique database,
migrates it and removes that owned database when its context exits.

From the repository root, build the frontend and start the retained fixture in
one PowerShell terminal. Use the locked interpreter selected for your checkout:

```powershell
npm --prefix apps/web ci
npm --prefix apps/web run build
$env:RECONFORGE_CASH_TEST_MIGRATION='0099_pg_receivables_policy'
$env:RECONFORGE_CASH_UI_OUTPUT='output/receivables-policy-browser-fresh'
$env:RECONFORGE_CASH_UI_PASSWORD='SyntheticPolicy-2026!'
$env:RECONFORGE_CASH_UI_PORT='24450'
python -m tests.receivables_policy_ui_runtime
```

The output directory must be fresh. Wait for `fixture.json`; it records the
owned database name and seeded source IDs. The fixture binds HTTPS to localhost
with a temporary test certificate. It seeds JPY0/KWD3, a large exact KWD invoice
and an explicitly unverified historical representation. Its administrative
legacy seeding is confined to that disposable database and restores guards in
the same transaction; public application routes cannot remove captured policy.

In a second terminal, use the same password/output variables, then run:

```powershell
$env:RECONFORGE_CASH_UI_BASE_URL='https://localhost:24450'
$env:RECONFORGE_POLICY_UI_BASE_URL='https://localhost:24450'
$env:RECONFORGE_CASH_UI_OUTPUT='output/receivables-policy-browser-fresh'
$env:RECONFORGE_CASH_UI_PASSWORD='SyntheticPolicy-2026!'
$env:RECONFORGE_WEB_PORT='4178'
npm --prefix apps/web run e2e -- e2e/receivables-cash-live.spec.ts e2e/receivables-policy-live.spec.ts --reporter=line
Set-Content -LiteralPath 'output/receivables-policy-browser-fresh/stop-owned-runtime' -Value 'stop'
```

Send the shutdown marker even if the browser command fails, and await fixture
exit. Retain its exit status, the browser exit status, `source-before.json`,
`fixture.json`, `persistence.json`, browser evidence and screenshots. Require
`source_changed=[]` and `database_removed=true`. Independently query the control
database's `pg_database` for the recorded owned database name and require absence.
Do not overwrite a failed attempt with a later successful one.

The USD journey tests lost receipt acknowledgement with exact retry and lost
allocation acknowledgement with authoritative GET recovery. JPY/KWD each create
a1234-minor Draft and post1000minor with500minor allocation; authoritative
remaining invoice balance is734minor after reload and explicit login. The large
KWD origin8999999999999999123 displays as8999999999999999.123KWD. The legacy1234
record stays labeled original minor units with financial writes unavailable.
English/Arabic Axe,390px width and keyboard evidence disclosure are recorded.

These optional specs report a prerequisite skip without the explicitly supplied
synthetic profile. A skip does not reproduce acceptance. Historical monetary
policy migration/restore, full Python regression and hosted gates remain separate
from this browser journey.
