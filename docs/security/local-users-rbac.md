# Local Users And RBAC

ReconForge now includes a local SQLite-backed users and RBAC foundation for DB-backed workflows.

This is a local-first foundation only. It does not add SaaS authentication, hosted identity, SSO, SCIM, SOC/ISO/SOX compliance, production enterprise identity, direct ERP connectors, legal sign-off, audit opinions, or digital signatures.

## What It Adds

- Local users stored in the ReconForge SQLite database.
- Password hashing with stdlib PBKDF2-HMAC-SHA256, per-user random salts, stored iteration counts, and constant-time verification.
- Built-in roles: `admin`, `controller`, `preparer`, `reviewer`, and `auditor-readonly`.
- Built-in permissions for user management, role management, DB read access, audit event read/verify access, reconciliation workflow primitives, control testing, evidence read access, and report read access.
- Role assignment and permission-check helpers for future DB-backed workflows.
- Separation-of-duties primitives for conflicts such as prepare/review and submit/approve on the same object.
- Audit events for local user and role mutations.

## CLI Commands

Initialize or migrate the DB first:

```bash
reconforge db init --db output/reconforge.db
```

Create the first local admin:

```bash
reconforge users init-admin --db output/reconforge.db --username admin
```

Create and manage local users:

```bash
reconforge users add --db output/reconforge.db --username reviewer --role reviewer
reconforge users list --db output/reconforge.db
reconforge users disable --db output/reconforge.db --username reviewer
reconforge users set-role --db output/reconforge.db --username reviewer --role auditor-readonly
reconforge users check-permission --db output/reconforge.db --username reviewer --permission audit.read
```

Inspect roles:

```bash
reconforge roles list --db output/reconforge.db
reconforge roles permissions --db output/reconforge.db --role reviewer
```

Password prompts use hidden interactive input. Do not pass passwords through shell history, scripts, logs, docs, fixtures, or generated output.

## Boundaries

- SSO and SCIM are not implemented.
- API authentication and Studio auth are not implemented in this slice.
- RBAC primitives are available for future workflow integration, but this does not make existing JSON workflows identity-enforced.
- Separation-of-duties checks are reusable primitives only until later workflow slices call them.
- Audit events provide checksum integrity aids for local mutations. They are not legal digital signatures or non-repudiation controls.
- This is not SOC, ISO, SOX, GDPR, audit, legal, tax, or regulatory compliance.
