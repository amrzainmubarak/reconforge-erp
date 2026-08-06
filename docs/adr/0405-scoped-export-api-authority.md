# ADR 0405: Expose scoped control-plane exports only through authenticated PostgreSQL server mode

- **Date**: 2026-08-06
- **Status**: Accepted
- **Context**: The deterministic scoped-export repository already enforced
  PostgreSQL row-level hierarchy bounds, but no API surface exposed its
  snapshot. A route must not accidentally turn the local SQLite profile or an
  unauthenticated request into an export authority.
- **Decision**: Add `GET /api/v1/exports/scoped` as a read-only server-profile
  boundary. It requires the existing `reports.read` permission, resolves the
  tenant/workspace/organization/legal-entity hierarchy from the authenticated
  principal, re-evaluates that permission centrally for the selected
  tenant/workspace/entity, and delegates to the RLS-backed PostgreSQL
  repository. The
  response carries the canonical artifact, digest, byte size, and an explicit
  server-mode source marker. No SQLite fallback, object-storage publication,
  presigned URL, or provider network call is introduced.
- **Verification**: The authenticated route contract test proves bearer
  authentication, hierarchy propagation, central permission re-evaluation,
  deterministic artifact digest, and the closed response envelope. The API
  authorization inventory includes the route and remains digest-addressed.
- **Boundary**: This proves only a bounded API composition around the existing
  repository. It does not prove live PostgreSQL availability, distributed IAM
  invalidation, object-store durability, worker/UI adoption, HA/DR, or
  production readiness.
- **Reversibility**: Remove the route, server helper, test, documentation, and
  manifest entries without a schema migration. Existing repository and
  publication contracts remain unchanged.
