# Organization And Fiscal Master Data

ReconForge includes a governed local foundation for organizations, legal entities, branches, currency references, and fiscal periods. The service is backed by SQLite migration 7, uses local RBAC permissions, appends mutation audit events, and exposes CLI plus authenticated `/api/v1/master-data` routes.

This is shared reference metadata for finance-control workflows. It is not a complete ERP company administration system, statutory entity registry, exchange-rate provider, consolidation engine, general ledger, or source-ERP posting lock.

## PostgreSQL server boundary

The explicit authenticated server profile routes currencies, organizations,
legal entities, branches, fiscal periods, summary, and the path-free snapshot to the
tenant-scoped PostgreSQL repository. PostgreSQL enforces tenant-aware foreign
keys and forced RLS. Mutation audit events and outbox records are appended in
the same caller-owned transaction as each write. The server response identifies
`source_backend: postgresql-master-data` for collection records.

Alembic revision `0005_postgres_fiscal_periods` adds the tenant-scoped fiscal
calendar table. Server-mode period list/create/status calls use this table and
the same audit/outbox contract. Period status is coordination metadata only; it
does not prevent postings in a source ERP or certify a close.

## Initialize or upgrade

```bash
reconforge db migrate --db output/reconforge.db
reconforge modules show platform.master-data
reconforge modules validate
```

Migration 7 is additive. It preserves existing workspace, organization, entity, and period rows; adds bounded legacy organization codes, activity/update metadata, a currency catalog, branches, fiscal metadata, indexes, and the `master_data.read` / `master_data.manage` permissions.

Back up the local database before applying migrations in an important environment.

## CLI workflow

```bash
reconforge master-data currency-upsert --db output/reconforge.db --code JPY --name "Japanese Yen" --minor-units 0
reconforge master-data organization-upsert --db output/reconforge.db --code SYN --name "Synthetic Group"
reconforge master-data entity-upsert --db output/reconforge.db --organization SYN --code JP01 --name "Synthetic Japan" --currency JPY
reconforge master-data branch-upsert --db output/reconforge.db --organization SYN --code TYO --name Tokyo --entity JP01
reconforge master-data period-upsert --db output/reconforge.db --name 2026-07 --start 2026-07-01 --end 2026-07-31

reconforge master-data currencies --db output/reconforge.db
reconforge master-data organizations --db output/reconforge.db
reconforge master-data entities --db output/reconforge.db --organization SYN
reconforge master-data branches --db output/reconforge.db --organization SYN
reconforge master-data periods --db output/reconforge.db
reconforge master-data summary --db output/reconforge.db
reconforge master-data snapshot --db output/reconforge.db
```

List commands accept bounded `--limit` and `--offset` options. The default limit is 500 records; the local service permits at most 100,000 records in one call.

`snapshot` prints the versioned, path-free JSON contract to standard output. Redirect it to a user-selected local file when desired:

```bash
reconforge master-data snapshot --db output/reconforge.db > output/organization_master_data.json
```

The contract schema is `docs/schemas/organization_master_data.schema.json`.

## Fiscal-period lifecycle

Allowed metadata transitions are:

```text
Open -> Soft Closed -> Closed
          |              |
          +----> Open <--+
```

Reopening requires a non-empty reason. Period date ranges cannot overlap inside the same workspace. Updates use a write lock around the overlap check, and status updates reject concurrent changes.

These statuses support control-workflow coordination only. They do not prevent postings in a source ERP, create accounting entries, certify a close, or provide legal/audit sign-off.

## Currency boundary

- Codes created through the service must be three uppercase letters.
- Minor units are bounded from 0 through 6.
- Legal entities may use only an active registered currency.
- The catalog contains no exchange rates, remeasurement logic, conversion provider, central-bank feed, or statutory localization.
- Existing legacy entity currency text is preserved during migration.

## Relationships and invariants

- Organization codes are unique per workspace.
- Entity codes are unique per organization.
- Branch codes are unique per organization.
- A branch can reference only an entity in the same organization.
- Names and codes are bounded and reject control characters.
- Reads do not create missing workspaces.
- Mutations append sanitized events to the local audit hash chain.
- Snapshots exclude database paths, credentials, sessions, evidence paths, and arbitrary file links.

## Permissions

| Permission | Default roles | Scope |
| --- | --- | --- |
| `master_data.read` | admin, controller, preparer, reviewer, auditor-readonly | Read lists, summary, and snapshot |
| `master_data.manage` | admin, controller | Create/update references and transition period metadata |

CLI calls with an actor matching a local username enforce these permissions. The default `local-cli` label preserves trusted local command compatibility and is recorded in audit metadata.

## Authenticated API

Read endpoints:

- `GET /api/v1/master-data/summary`
- `GET /api/v1/master-data/snapshot`
- `GET /api/v1/master-data/currencies`
- `GET /api/v1/master-data/organizations`
- `GET /api/v1/master-data/entities`
- `GET /api/v1/master-data/branches`
- `GET /api/v1/master-data/periods`

Mutation endpoints:

- `POST /api/v1/master-data/currencies`
- `POST /api/v1/master-data/organizations`
- `POST /api/v1/master-data/entities`
- `POST /api/v1/master-data/branches`
- `POST /api/v1/master-data/periods`
- `POST /api/v1/master-data/periods/{period_id}/status`

Mutation bodies reject unknown fields. API errors remain structured and do not expose raw SQLite errors or tracebacks.
List endpoints accept `limit` and `offset`, return a `pagination` object with the applied values and returned count, and cap one API page at 1,000 records. The default page size is 500.
