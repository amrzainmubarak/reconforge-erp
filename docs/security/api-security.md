# API Security

## Overview

ReconForge implements defense-in-depth API security aligned with the **OWASP API Security Top 10 (2023)** and **OWASP ASVS 5.0** standards. The platform enforces strict multi-tenant boundary checks, cryptographic route authorization indexing, and fail-closed network policies.

## Implemented Controls

### 1. Authentication & Session Management (API2, ASVS V6/V7)
- Local REST API sessions use opaque bearer tokens whose SHA-256 hashes are persisted in SQLite.
- Token resolution is bounded and validated per-request; raw session secrets are never exported or logged.
- Protected routes require explicit authentication and RBAC dependencies (`require_permission`, `require_any_permission`).

### 2. Broken Object Level Authorization (BOLA / IDOR) Defense (API1, ASVS V8)
- Every resource access is strictly bound to the authenticated caller's tenant identifier (`tenant_id`).
- PostgreSQL persistence enforces `FORCE ROW LEVEL SECURITY` with dynamic runtime role verification on every checkout.
- SQLite repositories enforce tenant filtering on all entity lookups.
- Negative tests in `tests/test_security_asvs_api_top10.py` assert that tenant B cannot access or observe objects owned by tenant A (failing closed with `PermissionError` / 403 / 404).

### 3. Server-Side Request Forgery (SSRF) Protection (API7, ASVS V12)
- Outbound network connectors (REST sources, S3 integrations, webhooks) enforce DNS pre-resolution via `reconforge.connectors.network.resolve_public_addresses()`.
- Disallowed address spaces are strictly rejected with `ConnectorNetworkError("connector_destination_not_public")`:
  - IPv4 loopback (`127.0.0.0/8`) and IPv6 loopback (`::1`)
  - Cloud provider metadata service endpoints (`169.254.169.254`, `169.254.0.0/16`)
  - RFC 1918 private IPv4 networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`)
  - IPv6 link-local addresses (`fe80::/10`) and unspecified addresses (`0.0.0.0`)
- DNS responses containing mixed public and private addresses fail closed.
- Verified in `tests/test_security_asvs_api_top10.py` and `tests/test_connector_network.py`.

### 4. Spreadsheet / CSV Formula Injection Defense (ASVS 5.0 V5.1.4)
- Tabular data exports (GL exports, trial balances, aging reports, exception queues) neutralize spreadsheet formula triggers.
- Cells beginning with `=`, `+`, `-`, `@`, or leading whitespace/control characters followed by these triggers are sanitized by prefixing with a single quote (`'`).
- Spreadsheet software (Microsoft Excel, LibreOffice Calc, Google Sheets) interprets sanitized cells strictly as text literals rather than executable DDE/hyperlink formulas.
- Verified in `tests/test_security_asvs_api_top10.py`.

### 5. Unrestricted Resource Consumption & Rate Limiting (API4)
- Sensitive authentication, posting, and batch operations are protected against burst traffic and resource starvation.
- Sliding-window rate limiting throttles requests exceeding thresholds with standard HTTP 429 (`Too Many Requests`) and `Retry-After` headers.
- Verified in `tests/test_security_asvs_api_top10.py`.

### 6. Route Authorization Inventory & Cryptographic Digest (API5)
- All 492 API routes are indexed in `reconforge/api/authorization.py` with an immutable SHA-256 surface digest (`14b516ccedc6622f05971c891af1ab1764ca1c31994aa5c22855b939c074cf83`).
- Unauthenticated or unauthorized route registration changes immediately fail CI via `tests/test_api_authorization_inventory.py`.

## Partially Implemented & Architecture Boundaries

- API coverage is bounded by implemented PostgreSQL and SQLite repositories; remaining domain workflows continue through tenant-isolated local SQLite.
- Role design is built-in and local; SCIM v2 / SSO / OIDC protocols are designed in schema but require external IdP configuration.
- Global API gateway ingress (WAF, edge TLS termination) is managed by deployment infrastructure rather than application code.

## Roadmap

- Production enterprise SSO (SAML 2.0 / OIDC) integration.
- Distributed token-bucket rate limiting backed by Redis.
- Automated API fuzzing and continuous dynamic security testing (DAST).
