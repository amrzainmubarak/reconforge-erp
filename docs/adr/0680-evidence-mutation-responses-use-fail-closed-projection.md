# ADR 0680: Evidence mutation responses use fail-closed projection

## Status

Accepted for the E-1020 slice on 2026-08-26.

## Context

Evidence record reads and drill-down already had reviewed projections, but the
Server Profile mutation endpoints for saving an evidence requirement and
recording a checksum verification returned adapter objects directly. That
made the response contract depend on every physical PostgreSQL column or
dataclass field and allowed an unreviewed future field to cross the API
boundary.

## Decision

1. Define closed allowlists for evidence requirement and checksum verification
   responses in `reconforge.auth.field_access`.
2. Apply the allowlists after the PostgreSQL adapter returns and before the
   response is serialized.
3. Preserve the known fields required by the authorized `evidence.manage` or
   `evidence.verify` operation. Add deterministic `field_access` metadata with
   projection version, denied fields, and digest.
4. Treat this as response contract hardening, not a substitute for permission,
   tenant scope, or transaction authorization. The existing permission and
   Server Profile tenant boundary remain mandatory.

## Evidence and limits

- `tests/test_field_access.py` covers both mutation allowlists and unknown
  adapter fields.
- `tests/test_api_server_evidence.py` covers the HTTP responses and additive
  projection metadata.
- This does not prove external IAM, distributed revocation, source
  authenticity, disclosure approval, or production effectiveness.

## Rollback

Revert E-1020 code/tests/ADR 0680/manifest and execution records together.
Do not restore direct adapter serialization without an approved versioned
response contract.
