# ADR 0789: Preserve hosted API routes and authentication errors

- Status: Accepted
- Date: 2026-10-03
- Owners: API / Studio

## Context

Authentication exceptions raised by middleware bypassed router error handlers
and became generic 500 responses. Browsers send session cookies on HTML/asset
requests but cannot attach the tenant API header there. The root SPA mount was
also registered before metrics and financial routers, shadowing those APIs with
HTML. Existing hosting checks exercised only the earlier health route.

## Decision

Bind authenticated principals on API namespace requests; static public application
resources carry no business data and do not require a tenant header. Convert
typed middleware APIError denials through the existing sanitized handler while
preserving request IDs and outer security headers.

Register the catch-all SPA after every API/SCIM router. Never serve SPA fallback
for unknown API/SCIM paths. Normalize OS-specific static path separators before
checking namespaces or file extensions.

## Verification and rollback

Seven new hosting regressions failed before the fix: cookie-bearing resources,
business route dispatch and unknown API fallback. The combined middleware/API
selection passes 32 tests with one explicitly capability-gated live skip.
The separate real hosted browser result is recorded in execution evidence.

No schema or API payload changes. Source rollback would restore the routing and
error defects. Vite development proxy success alone cannot validate production
same-origin hosting.
