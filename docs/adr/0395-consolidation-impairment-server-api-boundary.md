# ADR 0395: Consolidation impairment API is server-scoped and non-posting

## Context

The PostgreSQL impairment evidence adapter from ADR 0394 was usable only by
backend callers. A governed server deployment also needs an authenticated API
surface, while Community mode must not silently fall back to SQLite or expose
an accidental posting path.

## Decision

Expose:

- `POST /api/v1/consolidation-impairment` behind `finance_core.manage`; and
- `GET /api/v1/consolidation-impairment/{artifact_id}` behind
  `finance_core.read` or `finance_core.manage`.

The route accepts a closed Pydantic contract with canonical Money values,
rejects unknown fields and binary-float-shaped values, binds `prepared_by` to
the authenticated principal, requires an independent `approved_by`, and
re-evaluates the tenant policy before the PostgreSQL tenant boundary. It is
server-profile-only and fails closed with 503 when PostgreSQL is not configured.

## Evidence

- `tests/test_api_consolidation_impairment.py` covers authentication,
  server-only behavior, strict request reconstruction, authenticated actor
  binding, unknown-field refusal, read access, and tenant policy re-evaluation.
- `tests/test_api_authorization_inventory.py` records 241 route contracts and
  digest `4e456e05005444abe0e5a70c03f6d11177aa6629b58051e8ac773586b43158f2`.

## Boundary

The endpoint persists only the deterministic artifact with `posted: false`.
It does not choose valuation methodology or CGU scope, recognize statutory
impairment, post journals, call a provider, or establish production readiness.
