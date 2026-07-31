# Read-only network connector runtime

This runtime is an experimental SDK boundary, not a live vendor connector. It performs no network
activity until an operator supplies all of the following through a trusted composition root:

1. A schema-closed, signed connector manifest and active publisher public key.
2. A schema-closed registration whose endpoint exactly matches the manifest.
3. A secret resolver that accepts the registration reference and returns the credential only at execution time.
4. A durable-job repository, immutable object store, and scoped worker lease.

## Enforced boundary

- Read-only HTTPS GET; no write-back or redirect following.
- Exact endpoint allowlist; no URL credentials, query, or fragment.
- Public-only DNS answers and IP-pinned TLS connection with hostname verification.
- Disabled secret resolution by default; secret values are absent from persisted artifacts/results.
- Bounded idempotency keys, cursors, responses, retry attempts/delays, timeout, and per-process rate.
- Retry only for transport failures and HTTP 408/425/429/5xx.
- Each committed page binds request, response, manifest, registration, object, cursor, and durable-job digests.
- Crash/resume reads the latest committed artifact and skips previously committed effects.

## Verification

```powershell
uv run --locked python -m pytest tests/test_connector_network.py tests/test_connector_durable_workload.py
```

The tests use synthetic transports, credentials, SQLite, and local immutable storage. They perform
no external network call and contain no production secret or customer data.

## Operational limitations

- No vendor connector, OAuth token exchange, mTLS client identity, SFTP, database, event stream, webhook receiver, or write-back implementation is bundled.
- The injected secret resolver and trust registry must be governed by the deployment; no production vault integration is claimed.
- Rate state is process-local, not a distributed provider quota.
- Provider schemas and business semantics require connector-specific conformance and human review.
- No external penetration test, provider interoperability, HA/DR, compliance, certification, or Enterprise-readiness claim exists.
