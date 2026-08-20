# ADR 0376: Preserve FinanceRead any-of semantics in server scope checks

- **Date**: 2026-08-06
- **Status**: Accepted
- **Decision**: Keep the second server-scope authorization check for Finance
  Core read routes aligned with the route dependency's any-of contract:
  `finance_core.read`, `finance_core.manage`, or `finance_core.validate`.
  Manage and write routes retain their exact permission checks.
- **Context**: A validation-only emergency grant passed the initial
  `FinanceRead` dependency but was then incorrectly narrowed to
  `finance_core.read` by `_server_finance_workspace`, denying an authorized
  request. The same defect blocked the WebAuthn live summary path.
- **Verification**: On a fresh PostgreSQL 17.10 migration-head database with
  a non-privileged role, the selected live API suite passed 24/24, including
  emergency-access activation/use/review, WebAuthn MFA/step-up, the legacy
  server-identity compatibility path, federation, SCIM, service accounts, and
  application metrics.
- **Boundary**: This closes a route authorization-consistency defect only. It
  does not claim complete enterprise IAM, federation interoperability, live
  ERP/bank connectivity, write-back, HA/DR, or production readiness.
- **Rollback**: Restore the previous exact-read check and remove this evidence
  entry; no data migration is required.
