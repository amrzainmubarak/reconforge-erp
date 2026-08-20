# ADR 0316: Live authenticated consolidation ownership API gate

- Status: accepted
- Date: 2026-08-04

## Decision

Extend the existing live PostgreSQL server-identity fixture with the
consolidation ownership schema, least-privilege table grant, and authenticated
API assertions. The fixture creates an ownership revision through
`POST /api/v1/consolidation-ownership/interests`, resolves it through
`GET /effective`, and attempts a sibling-workspace read that must fail before
repository access. It uses synthetic tenant/user data and a non-superuser,
non-BYPASSRLS PostgreSQL application role.

## Rationale

The route and repository contracts were already covered locally, but mocked
scope wiring was not enough to prove the actual FastAPI middleware, server
identity, request scope, PostgreSQL RLS, and ownership adapter work together.
Reusing the established server-identity fixture gives one reproducible runtime
gate without creating a second identity harness.

## Security and financial boundary

The test verifies authorized workspace selection, authenticated preparer
binding, exact decimal wire input, PostgreSQL persistence/replay, and sibling
workspace refusal. It does not prove production HA, independent approver
authentication beyond the declared identity value, statutory consolidation,
live ERP/bank providers, or production readiness.

## Compatibility and rollback

No migration or public schema changes are introduced; the fixture explicitly
installs the existing ownership schema and grants only the table operations it
needs. Rollback removes the fixture additions and this ADR; the API and
ownership persistence remain available.
