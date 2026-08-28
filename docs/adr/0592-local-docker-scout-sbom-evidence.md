# ADR 0592: Record local Docker Scout SBOM as bounded evidence

## Status

Accepted — 2026-08-23

## Decision

Generate a CycloneDX SBOM from the explicit `local://reconforge:current` image
with Docker Scout, retain the generated JSON in the run output, and record its
component count, byte size, SHA-256, and command in execution evidence.

## Boundary

The generated SBOM is local image inventory evidence. It does not replace the
release SBOM pipeline, signed provenance, registry attestation, vulnerability
database freshness review, license policy, or hosted artifact verification.

## Rollback

Remove the dated execution note and ADR; no runtime or schema migration is
needed.
