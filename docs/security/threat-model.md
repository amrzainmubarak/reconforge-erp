# Threat Model

Implemented controls:

- Local path validation for DB and bridge operations.
- Safe JSON/YAML handling in core workflows.
- HTML escaping in generated Studio tables and pages.
- Hashed local sessions and no raw token storage.
- Audit event hash chain for DB workflow actions where practical.
- Security headers and login throttling for API auth route.

Primary assumptions:

- The user controls the local machine, filesystem, and DB path.
- Local backups and output folders are protected like sensitive finance data.
- Studio/API are intended for trusted local or self-hosted networks, not public internet exposure.

Partially implemented:

- RBAC and SoD are applied for implemented DB/API/Studio actions when actor usernames map to local users.
- Trusted local CLI mode can still perform actions without local user records.

Roadmap:

- Stronger deployment boundary checks.
- More complete workflow policy configuration.

Not supported:

- Internet-facing hardening guarantees.
- Legal non-repudiation.
- External audit assurance.
