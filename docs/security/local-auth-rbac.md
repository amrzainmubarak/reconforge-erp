# Local Auth And RBAC

Implemented:

- Local users with PBKDF2 password hashing.
- Built-in roles: admin, controller, preparer, reviewer, auditor-readonly.
- RBAC permissions for DB, users, roles, audit, workflow, account reconciliation, close, approvals, evidence, journals, intercompany, controls, matching, exceptions, metrics, and ops.
- Studio auth-required mode and local API bearer sessions.

Partially implemented:

- SoD checks exist for workflow transitions and selected finance lifecycle actions.
- Trusted local CLI labels can still operate without a user record.

Roadmap:

- Configurable role policies.
- SSO/OIDC/SAML and SCIM design before implementation.

Not supported:

- External identity provider integration.
- Production SaaS identity.
- Legal approval signatures.
