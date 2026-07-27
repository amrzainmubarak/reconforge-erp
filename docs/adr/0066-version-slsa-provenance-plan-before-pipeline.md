# ADR 0066: Version the SLSA Provenance Plan Before Building the Pipeline

- Status: Accepted
- Date: 2026-07-25
- Decision owner: Release Security

## Context

SLSA 1.2 is the current Approved specification and adds the Source Track beside
the Build Track. ReconForge has build, Docker, SBOM, security, CodeQL, and
release-document definitions, but it does not generate or verify release-bound
SLSA provenance. Adding a signing action without first fixing artifact,
builder, attestation, verification, failure, and rollback contracts would
create cryptographic output with ambiguous trust and unsupported level claims.

## Decision

Adopt a closed schema-v1 implementation plan pinned to official SLSA 1.2 tag
and commit. Keep Build and Source results `UNEVALUATED` and publish no verified
properties. Define exact wheel, sdist, OCI image, and CycloneDX SBOM identities;
seven trust boundaries; in-toto Statement v1/SLSA provenance v1 fields;
signature expectations; fail-closed verification; safe error codes; evidence-
preserving rollback; and 12 implementation gates with owners and testable exit
criteria.

Treat the current source/tag and build-definition gates as partial and the
other ten as planned. P0-SEC-006 may implement the signed pipeline only against
this contract and must not claim a SLSA level without an artifact-specific,
platform-specific assessment and verifier evidence.

## Consequences

- Source/spec drift, artifact/boundary/gate omissions, dangling evidence or
  owners, unsafe attestation fields, verifier failure drift, and accidental
  level promotion fail contract tests.
- Provenance generation/signing is explicitly outside tenant-defined build
  steps; a repository workflow cannot self-assert its builder trust.
- Verification expectations are independent from provenance content and fail
  closed. Retry without a reviewed input/policy/identity change is prohibited.
- Rollback preserves immutable forensic records and links affected/replacement
  digests instead of overwriting releases.
- This slice changes governance artifacts only. It does not create a release,
  signature, attestation, source-control rule, trusted builder, or SLSA claim.

## Compatibility and rollback

No runtime, API, package, image, CI execution, or release behavior changes.
Use a versioned successor if the Approved spec, attestation format, artifact
set, builder, signer, verifier, or rollback contract changes. Removing the plan
removes only governance; it cannot revoke or validate artifacts because none
are created by this slice. Never roll back by weakening verification or
relabeling `UNEVALUATED` as a level.
