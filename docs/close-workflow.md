# Close Workflow

ReconForge provides a local close checklist workflow for lightweight month-end coordination. It writes a JSON checklist and local reports only. There is no SaaS workflow, cloud upload, authentication, notification system, or database.

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

## Security Notes

- Checklist files are read from and written to local paths.
- Owners are plain text. They are not users, roles, or access-control principals.
- HTML report values are escaped before rendering.
- Malformed checklist JSON produces a controlled CLI error instead of a traceback.
- Do not put secrets, credentials, or live customer data in demo checklist templates.
