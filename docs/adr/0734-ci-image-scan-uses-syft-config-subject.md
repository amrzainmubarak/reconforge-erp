# ADR 0734: Bind CI image scans to Syft's configuration subject

- **Status**: Accepted
- **Date**: 2026-08-28
- **Decision owners**: ReconForge maintainers

## Context

The container security and release workflows build a Linux AMD64 image with
BuildKit attestations enabled. `docker image inspect --format '{{.Id}}'` can
return the local manifest-list identity, while Syft's native image SBOM records
the image configuration digest as `source.metadata.imageID` and the platform
manifest separately. Passing the former to the exact-subject validator makes a
valid scan appear mismatched and weakens the evidence boundary if the two
identities are treated as interchangeable.

## Decision

After Syft writes the native SBOM, both workflows call
`.github/scripts/extract_syft_image_config_digest.py`. The helper accepts only
a native image document whose configuration digest and manifest digest are
canonical SHA-256 values and whose platform is exactly `linux/amd64`. The
returned `imageID` is used for the Grype evidence, retained security evidence,
and post-push configuration binding. The manifest digest remains in the SBOM
and is independently checked by the existing policy validator.

The workflows no longer infer the scan subject from Docker's local `.Id`.
This keeps the scan, evidence, and publication checks bound to the same
subject emitted by the inventory tool.

## Consequences

- BuildKit manifest-list and image-configuration identities cannot silently
  drift at the workflow hand-off.
- Malformed, non-image, non-SHA-256, or non-Linux-AMD64 Syft documents fail
  closed before Grype evidence is accepted.
- The helper is intentionally narrow and does not claim OCI reproducibility,
  signed provenance, registry publication, or production security.
- Existing workflow output keys and the release/publication order remain
  compatible; only subject extraction is corrected.

## Verification and rollback

The helper's valid, malformed-platform, workflow wiring, supply-chain policy,
signed-release, and container-hardening tests pass. Ruff, Mypy, the supply-chain
policy validator, and source YAML validation pass. Roll back this decision by
reverting E-1074, ADR 0734, the helper, manifest entry, and associated tests as
one change; do not restore an unvalidated Docker `.Id` subject hand-off.
