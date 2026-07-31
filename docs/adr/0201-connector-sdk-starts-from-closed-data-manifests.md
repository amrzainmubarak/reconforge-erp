# ADR 0201: Connector SDK starts from closed data manifests

- Status: Accepted
- Date: 2026-07-30
- Task: P3-ENT-007

## Context

The historical `reconforge.plugins` surface contains a generic local CSV adapter and two
vendor-shaped export profiles. It uses a static registry, but its protocol does not declare
security, network, secret, cursor, retry, or support boundaries. Calling the SAP and Odoo
profiles live connectors would be inaccurate.

## Decision

Introduce `connector-manifest-v1` as a strict, immutable data contract. Version 1 is read-only
and rejects write capability. It binds stable identity and semantic version, kind, authentication,
network use, data classification, rate limit, cursor and idempotency behavior, bounded retry,
input schema versions, synthetic sandbox support, threat-model references, secret handling,
exact egress destinations, and support level. Canonical JSON and SHA-256 produce a deterministic
content digest; that digest is integrity metadata and is not a package signature.

The built-in registry remains a source-code allowlist and does not import entry points, paths, or
user-supplied modules. The SAP and Odoo implementations declare `export_profile`; the generic CSV
implementation declares `local_file`. A backend-neutral conformance function verifies manifest
policy, read-only behavior, unchanged synthetic inputs, accepted schema, and non-empty output.
External declarations use a bounded, closed JSON envelope authenticated with Ed25519 against one
exact operator-provided publisher/key identity. The envelope cannot name executable entry points.

## Consequences

- Existing `list_connectors()` and `get_connector()` names remain compatible.
- No network, credential, write-back, direct ERP integration, or vendor certification is added.
- A digest does not authorize installation. The signed envelope authenticates manifest data only;
  it does not install code. Compatibility approval and executable connector distribution remain
  disabled until a separately governed sandbox design exists.

## Rollback

Remove `reconforge.connectors`, manifest attributes, and the conformance test. The historic static
adapter registry and local export workflow remain usable; no database or user data migration exists.
