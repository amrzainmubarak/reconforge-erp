# Connector SDK foundation

ReconForge currently provides one local CSV adapter and two local export profiles. It does not
provide live SAP/Odoo connectivity, credential handling, synchronization, or write-back.

Every implementation entering the SDK must carry a validated `connector-manifest-v1`. The first
schema deliberately permits read-only implementations only. Local adapters declare no authentication,
network rate limit, or egress destination. A future network-source slice must require explicit
authentication, exact egress policy, rate limits, a network sandbox, secret references rather than
secret values, cursor and retry tests, and operator authorization.

Run the current synthetic local conformance boundary with:

```powershell
uv run --locked python -m pytest tests/test_connector_sdk.py
```

The test verifies the static allowlist, truthful adapter kinds, deterministic manifest digest,
closed fields, denial of write capability and inconsistent egress/authentication declarations,
unchanged input files, schema acceptance, and non-empty datasets.

`tests/test_connector_package.py` verifies the data-only package envelope. It is capped at 64 KiB,
schema-closed, and authenticated with Ed25519 against an exact operator-provided publisher/key pair.
Changing the manifest, publisher, signature, or adding an executable entry point fails closed. This
verifies manifest provenance; it does not install or execute connector code.

Install signature verification explicitly with `pip install 'reconforge-erp[connectors]'`. Without
that optional standards-library dependency, signed-package verification fails closed with
`connector_signature_runtime_unavailable`; local built-in export adapters remain available.

## Current limitations

- No external package installation or dynamic code loading.
- Trust input is versioned and supports active/revoked keys, but persistent administrative approval remains deployment-owned.
- A provider-neutral read-only HTTPS runtime now has DNS/SSRF, TLS pinning, secret-reference, cursor, idempotency, retry, rate, and durable-job recovery tests; no live vendor registration or production secret resolver is bundled.
- Process-local rate state does not prove a shared distributed provider quota.
- No write-back path; manifest v1 rejects it.
- No executable external connector installation, vendor certification, direct ERP connector, or production deployment claim.
