# ADR-0646: Make API version scope backend-aware

- Status: Accepted
- Date: 2026-08-26
- Scope: E-953

## Context

The unauthenticated `/api/v1/version` response always returned
`local/self-hosted foundation`, even when PostgreSQL Server Profile was
enabled. Together with the previously corrected health response, this made
the public operational metadata describe the wrong deployment profile.

## Decision

Keep the package version, API version, and Local Profile scope unchanged.
Select the scope label from the explicit server capability and return
`postgresql server/self-hosted foundation` for PostgreSQL Server Profile.
The response remains unauthenticated and does not expose DSNs, hosts, or
connection details.

## Consequences

- Monitoring and support tooling can distinguish the Local and PostgreSQL
  server profiles without inspecting deployment secrets.
- This is metadata only; it does not claim PostgreSQL schema completeness,
  hosted availability, HA/DR, production readiness, compliance, or
  certification.

## Rollback

Revert the route, regression, and documentation changes. No schema or
persisted-data change is introduced.
