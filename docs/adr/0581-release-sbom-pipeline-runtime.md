# ADR 0581: Release manifest and SBOM pipeline runtime evidence

## Status

Accepted — 2026-08-23

## Decision

Retain the current local release pipeline contract as evidence when the
manifest/SBOM, signed-release, and SLSA-plan suites pass together. The pipeline
must validate exact release identities, artifact subject digests, deterministic
CycloneDX output, source/package/image binding, tamper rejection, forbidden
paths, and closed workflow expectations.

## Limits

This evidence validates repository-controlled builders and contracts only. It
does not provide a signed attestation, trusted hosted-builder assessment,
published SBOM, registry signature, SLSA level, or independent provenance
verification. The optional `cyclonedx-py` host utility was not counted because
the local installation is missing `chardet`.
