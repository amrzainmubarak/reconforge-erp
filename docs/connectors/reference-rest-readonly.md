# Reference REST read-only connector

`reconforge.connectors.rest_reference.ReferenceRestConnector` is a provider-neutral, synthetic reference integration. It is intentionally not a live ERP or bank connector.

The connector runs through the existing network boundary: operator-owned secret references, exact HTTPS egress allowlists, public-address SSRF checks, bounded response bytes, retries, rate limiting, cursors, idempotency keys, and read-only capability. The response contract is closed JSON:

```json
{"records":[{"id":"R-1","amount":"10.00","currency":"USD","date":"2026-01-01","partition":"AR"}],"next_cursor":"cursor-2"}
```

Amounts must be finite exact Decimal text; record IDs are unique; unknown fields, duplicate IDs, non-finite values, and malformed dates fail closed. The adapter returns request and canonical response digests plus attempt count. It never stores credentials, posts data, follows redirects, or mutates source state.

Use `reference_rest_registration()` with a secret reference and `ReferenceRestConnector.read_page()` in synthetic conformance tests. Production provider registration, credential provisioning, legal/provider contracts, and write-back remain outside this reference slice.
