# Close Workflow

ReconForge provides a local close checklist workflow for lightweight month-end coordination. The CLI writes a JSON checklist and local reports. The authenticated API also has a bounded PostgreSQL close-control profile for tenant-scoped close metadata.

The close checklist is workflow metadata only. It is not an audit opinion, legal sign-off, compliance certification, tax advice, or digital signature.

## Commands

Create a default checklist:

```bash
reconforge close init --output output/close
```

List tasks:

```bash
reconforge close list --input output/close
```

Update a task:

```bash
reconforge close set-status --input output/close --task-id CLOSE-001 --status Complete --owner "Finance Controller" --note "Reviewed"
```

Export a close report:

```bash
reconforge close report --input output/close --output output/close_report
```

Outputs:

- `output/close/close_checklist.json`
- `output/close_report/close_report.html`
- `output/close_report/close_report.xlsx`
- `output/close_report/close_report.csv`
- `output/close_report/close_report.json`
- `output/close_report/close_summary.md`

## Statuses

Allowed statuses are:

- Not Started
- In Progress
- Blocked
- Complete
- Not Applicable

Status values are validated before the JSON state file is updated.

## Templates

You can initialize from a local JSON or YAML template:

```bash
reconforge close init --output output/close --template config/close-template.yml
```

Template files must contain a `tasks` list. Each task can include:

- `task_id`
- `task_name`
- `category`
- `owner`
- `due_date`
- `status`
- `note`

YAML templates are parsed with safe loading.

## Authenticated API close-control profile

When the API is created with the explicit PostgreSQL server profile, the close
routes persist `close_periods`, `close_tasks`, and task dependencies in the
tenant-scoped PostgreSQL schema. A close period references an existing
PostgreSQL fiscal period and organization. The server profile creates five
starter tasks with deterministic IDs, computes readiness, blocks completion
when dependencies are incomplete, requires full readiness before approval or
locking, and requires a reason to reopen.

Readiness is derived from integer task counts with an exact two-decimal Decimal
percentage (`ROUND_HALF_UP`). Approval and locking require exact `100.00`
readiness; an incomplete or unexpectedly represented value fails closed rather
than being rounded through binary float.

These are ReconForge workflow states only. A `Locked` close-control record does
not prevent postings in a source ERP and is not a statutory close, legal
certification, or digital signature. Server mutations append hash-chained audit
and transactional-outbox evidence and do not fall back to tenant-local SQLite.

## Security Notes

- Checklist files are read from and written to local paths.
- Owners are plain text. They are not users, roles, or access-control principals.
- HTML report values are escaped before rendering.
- Malformed checklist JSON produces a controlled CLI error instead of a traceback.
- Do not put secrets, credentials, or live customer data in demo checklist templates.
