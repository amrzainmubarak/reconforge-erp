# API Security

Implemented:

- Local REST API sessions use bearer tokens whose hashes are stored in SQLite.
- Protected routes require authentication and RBAC dependencies.
- API errors are structured and sanitized.
- Implemented account, close, exception, metric, workflow, audit, user, and role routes are local DB-backed.
- An explicit experimental server profile binds tenant-scoped PostgreSQL sessions/principals and routes bounded identity, master-data, ledger, close, audit, evidence-metadata, and reconciliation operations to PostgreSQL repositories.

Partially implemented:

- API coverage is not complete for every CLI workflow.
- Role design is built-in and local; it is not SSO or SCIM.
- PostgreSQL coverage is bounded by implemented repositories; remaining domain routes continue through tenant-isolated local SQLite rather than silently falling back across profiles.

Roadmap:

- Complete repository/route coverage and end-to-end tenant/principal tests before any hosted API claim.
- Optional SSO design review before implementation.

Not supported:

- OAuth/OIDC/SAML login.
- Public API gateway hardening.
- Raw token export.
