# ReconForge Studio

ReconForge Studio is the local web interface for reviewing validation, reconciliation, rule, WIP, evidence, and report outputs. It is intentionally lightweight and server-rendered so it does not require a frontend build system.

## Start Studio

```bash
reconforge studio --input examples/sample_data --output output
```

Then open the local URL printed by the CLI. The Studio runs with FastAPI and reads local files only.

Trusted local mode is the default. To require local sign-in, initialize a migrated ReconForge DB, create a local user, and start Studio with auth enabled:

```bash
reconforge db init --db output/reconforge.db
reconforge users init-admin --db output/reconforge.db --username admin
reconforge studio --input examples/sample_data --output output --require-auth --db output/reconforge.db
```

Auth-required mode uses the local users, roles, and hashed session-token foundation. It rejects disabled users, stores only session token hashes in the DB, and sends the browser session token only as an HTTP-only cookie. The exception review update action requires the user's local role to include `reconciliation.review`. Studio remains local-first and does not add SSO, SCIM, SaaS identity, hosted storage, telemetry, or direct ERP connectivity.

## Pages

| Page | Purpose |
| --- | --- |
| Home | Status, KPIs, and navigation |
| Dataset Health | Input file counts and structural health |
| Validation | Validation report summary where available |
| Reconciliation | Stock/GL and work-order result links |
| Exceptions | Filterable exception view with local review status |
| Close | Read-only local close checklist summary and task register when `output/close/close_checklist.json` exists |
| Variance | Read-only local variance table when `output/variance/variance_analysis.csv` exists |
| Control Matrix | Read-only local control matrix when `output/control_matrix/control_matrix.csv` exists |
| WIP Aging | Aging buckets and stale work orders |
| Control Packs | Rule engine result summaries |
| Evidence | Evidence coverage metrics and links to generated evidence binder case folders |
| Downloads | Links to generated Excel, Markdown, CSV, JSON, and HTML reports |
| Docs | Local documentation entry points |

## Recommended Workflow

1. Run the one-command demo or generate reports from the CLI.
2. Start Studio against the same output folder.
3. Open **Exceptions**.
4. Update review status, reviewer, notes, decision reason, accepted-risk reason, or escalation owner.
5. Filter exceptions by risk, status, type, source file, amount, work order, product, and search text.
6. Export the review register from the CLI when the review state is ready.

Studio is a review companion, not a separate data store. The authoritative outputs remain the generated files in the output directory. Close, variance, and control matrix pages are read-only foundations.

## Exception Filters

The Exceptions page can filter by severity/risk level, exception type, review status, source file, search text, and minimum amount impact. It can sort by risk score, amount impact, or review update date when those fields are available.

Review status is read from and written to `output/review_state.json`. Use the Studio form or CLI to update local state:

```bash
reconforge review set-status --input output --exception-id EXC-0001 --status "Under Review" --reviewer "Amr" --note "Checking source records"
```

## 10-Minute Demo

```bash
reconforge demo run --output output/demo
reconforge studio --input examples/sample_data --output output/demo
```

Open **Exceptions**, change `EXC-0001` or another visible exception, then filter by the selected review status. In trusted local mode, Studio validates allowed statuses and uses a simple local form token. In auth-required mode, users must sign in and the review update action also checks local RBAC.

## Review Fields

Studio can update:

- `exception_id`
- `status`
- `reviewer`
- `note`
- `decision_reason`
- `accepted_risk_reason`
- `escalation_owner`

Rendered values are escaped before display. Invalid statuses are rejected. Existing review entries are preserved when another exception is updated.

## Local Security Boundary

Studio binds to `127.0.0.1` unless another host is provided. Trusted local mode remains the default for single-user local review. `--require-auth` adds local DB-backed login, logout, HTTP-only session cookies, disabled-user rejection, and an RBAC check for the review-status mutation.

This is not SSO, OAuth, SAML, SCIM, production SaaS identity, legal approval, digital signature, non-repudiation, or compliance certification. Use Studio on trusted machines and trusted networks, and keep generated output folders and the local DB protected like sensitive finance control evidence.
