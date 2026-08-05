# ADR 0247: Reference connector manifests share one conformance gate

- **Status:** Accepted
- **Date:** 2026-08-02

## Decision

Run one deterministic portfolio check over the five provider-neutral reference
manifests: REST, payment statement, SFTP, object storage, and database. Every
manifest must be read-only, synthetic-sandbox capable, idempotent, schema and
threat declared; network sources must use either explicit public no-auth or
secret-reference authentication and an explicit egress allowlist. Database,
SFTP, object-storage, and payment reference registrations remain credentialed.

## Boundary

This closes the shared manifest safety contract only. It is not a live vendor
connector, provider interoperability, credential-vault, write-back, or
production network certification.
