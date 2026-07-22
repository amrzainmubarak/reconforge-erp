# ReconForge Security Architecture (Conservative Baseline)

This document describes the current security design for the local-first ReconForge
implementation and the controls that are implemented in code today.

## Boundaries

- **CLI paths**: File ingestion and report generation operate on user-supplied local paths.
- **API layer**: Optional HTTP surface for local/managed workflows.
- **Studio**: Local web UI built on Flask with session and authorization guards.
- **Storage**: SQLite database for local state, review history, and audit events.
- **Reporting/evidence**: Deterministic local artifact generation.

## Trust assumptions

- Files, paths, and output directories are under the local operator's control.
- Database and workspace access is restricted to trusted local users or trusted deployment hosts.
- No remote automatic financial data upload is part of core execution.

## Implemented controls

- **Path safety**:
  - Workspace and output path handling is validated against expected base directories.
- **Session handling**:
  - Password/session secrets are hashed/encoded.
  - Session records are stored in local persistence with bounded actions.
- **Input validation**:
  - CSV and YAML parsing is guarded and exceptions are surfaced instead of being
    silently converted.
- **Output hardening**:
  - HTML rendering in generated tables uses escaping for user-provided fields.
- **Request controls**:
  - Login throttling and simple rate-limiting behavior is implemented for auth routes.
- **Auditability**:
  - Security-relevant actions emit audit-style events and are persisted locally.

## Risk controls in practice

- Invalid financial amounts are treated as data-quality exceptions instead of becoming
  zero silently.
- Empty exception aggregation paths in exception collectors are guarded so clean runs do
  not crash.
- Matching and evidence generation paths are deterministic by design to reduce
  non-reproducible review disputes.

## Not-yet-implemented by design

- Internet-facing hardening profile for public deployments.
- Full tenant isolation guarantees for hosted multi-tenant mode.
- Complete formal SoD enforcement for every possible workflow action.
- Cryptographic non-repudiation or legal-grade assurance guarantees.

## Change and verification rules

- Update this document whenever new persistence, API, or auth behavior is introduced.
- Treat any new control as implemented only after corresponding tests exist.
- Do not claim additional guarantees (for example, audit/compliance certification)
  without explicit feature and test evidence.
