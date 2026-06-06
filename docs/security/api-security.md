# API Security

Implemented:

- Local REST API sessions use bearer tokens whose hashes are stored in SQLite.
- Protected routes require authentication and RBAC dependencies.
- API errors are structured and sanitized.
- Implemented account, close, exception, metric, workflow, audit, user, and role routes are local DB-backed.

Partially implemented:

- API coverage is not complete for every CLI workflow.
- Role design is built-in and local; it is not SSO or SCIM.

Roadmap:

- More route coverage for journals, intercompany, evidence registry, controls, and matching.
- Optional SSO design review before implementation.

Not supported:

- OAuth/OIDC/SAML login.
- Public API gateway hardening.
- Raw token export.
