# Security Questionnaire

Implemented:

- Local-first file and SQLite workflows.
- Local users, password hashing, RBAC roles, session-token hashing, and optional Studio auth-required mode.
- Append-only audit event hash chain.
- Sanitized DB export that excludes credential and session material.
- Local backup/restore with checksum manifest.

Partially implemented:

- DB-backed finance workflow RBAC and SoD checks for known local users.
- Local API authentication and RBAC for implemented API routes.
- Studio DB workflow pages with auth-required support for protected actions.

Roadmap:

- SSO/OIDC/SAML design and optional implementation.
- SCIM design.
- More granular workflow permissions and policy configuration.

Not supported:

- SOC 2, ISO, SOX, GDPR, or regulatory certification claims.
- Public SaaS hosting.
- Direct ERP credential handling or live connectors.
- Digital signatures or non-repudiation.
