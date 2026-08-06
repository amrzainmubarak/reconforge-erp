# Connector SDK foundation

ReconForge provides one local CSV adapter, two local export profiles, and governed read-only
reference connectors for REST, SFTP, object storage, databases, payment statements, ERP-shaped
ledger pages, and the World Bank public dataset. It does not provide live SAP/Odoo or bank-vendor
connectivity, synchronization, or write-back.

Every implementation entering the SDK must carry a validated `connector-manifest-v1`. The first
schema deliberately permits read-only implementations only. Local adapters declare no authentication,
network rate limit, or egress destination. A future network-source slice must require an explicit
authentication mode (public no-auth or secret-reference), exact egress policy, rate limits, a network
sandbox, secret references rather than secret values for credentialed sources, cursor and retry tests,
and operator authorization.

The concrete `world-bank-public-readonly` reference is intentionally narrower than a vendor
integration. It pins World Bank dataset `DS01556` / resource `RS00963` to three exact JSON page
URLs, uses public no-auth HTTPS, validates a closed finite-Decimal row schema, and emits request
and canonical response digests. Run its deterministic contract with:

```powershell
uv run --locked python -m pytest tests/test_connector_world_bank_public.py
```

The live page check is opt-in (`RECONFORGE_TEST_PUBLIC_NETWORK=1`) because public source
availability can drift. A successful run is interoperability evidence, not a freshness guarantee,
vendor SLA, bank/ERP integration, or production approval.

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
- A provider-neutral read-only HTTPS runtime now has DNS/SSRF, TLS pinning, public no-auth/secret-reference
  isolation, fixed-query preservation, cursor, idempotency, retry, rate, and durable-job recovery tests;
  no live vendor registration or production secret resolver is bundled.
- Process-local rate state does not prove a shared distributed provider quota.
- No live vendor write-back. The opt-in transport package has a separate,
  provider-specific idempotency-status recovery boundary that can acknowledge a
  possibly accepted mutation without issuing a second POST; manifest v1 still
  rejects executable external connector packages and no provider status API is
  bundled.
- No executable external connector installation, vendor certification, live vendor connector, or production deployment claim.
