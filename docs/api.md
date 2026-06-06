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
