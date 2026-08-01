# ADR 0207: Offline attestation trust is pinned and OCI-bounded

- Status: accepted
- Date: 2026-07-30

## Context

Checksum-only offline media cannot prove who signed an artifact. Conversely, allowing a
verifier to fetch trust or subject material during an alleged air-gap drill invalidates
the no-network boundary. GitHub CLI 2.78.0 can verify local file subjects from local
Sigstore bundles and a custom trusted root, but still resolves OCI subjects at the
registry even when their bundles are local.

## Decision

Disconnected verification pins both the verifier executable and trusted-root snapshot
by SHA-256, validates a closed checksum inventory, and invokes the verifier with exact
repository, workflow, signer commit, source tag, source commit, and hosted-runner
constraints. No shell or network fallback is permitted. Regular-file provenance and
SBOM attestations may pass. OCI bundle integrity and OCI subject verification are two
separate outcomes; the latter remains unverified when the tool requires registry access.

## Consequences

E-216 establishes real offline cryptographic trust for the source archive, wheel, sdist,
release metadata, checksum inventories, and SBOM files. It does not establish offline OCI
subject verification, physical transfer custody, trusted-root freshness beyond the pinned
snapshot, repeated-platform evidence, compliance, certification, or production readiness.

## Rollback

Quarantine the evidence set when any checksum, identity, signature, tool digest, or trust
root digest fails. Removing this verifier changes no installed runtime or published asset.
