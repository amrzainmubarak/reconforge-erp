# ADR 0802: Build a pinned MinIO source fixture for synthetic CI

Date: 2026-10-03

Status: Implemented for Draft CI verification; source-image runtime pending

## Context

The existing object-storage job cannot pull its historical MinIO image digest.
The official mirror did not provide it either. This preexisting dependency
failure prevents the real provider tests from running. Upstream MinIO is archived
and unmaintained; its source is used here only as a disposable synthetic fixture.

## Decision

Build the official immutable release source using a digest-pinned Docker Official
Go toolchain. Verify the source archive SHA256 before processing it, module locks
before and after compilation, and the resulting release/commit/Go identity.
Record source, license, recipe, manifest and module-lock provenance. Run the
separate nonroot scratch image by its OCI config digest on localhost with a
read-only root filesystem, no capabilities and disposable tmpfs storage.

Retain the actual S3 and Object Lock tests. The report adds an optional explicit
digest-kind field; existing reports remain compatible. The closed fixture
manifest is separate from the unchanged central supply-chain policy, whose
validator passes with no exception. The fixture is not shipped as a ReconForge
product image, does not change MIT licensing and does not designate a supported
production storage provider.

## Verification status and rollback

Fixture/report tests pass (28). Adapter/policy checks pass (50), with three
explicit environment skips. Ruff, Mypy, Bandit and policy validation pass.
An actual probe of the cached original MinIO release under the new runtime
restrictions passes all five storage invariants; 18 adapter tests pass with one
Windows symlink-privilege skip. This supplemental probe does not prove the new
source image builds.

The local source build timed out after 1800 seconds downloading the official
builder. No compilation occurred. Draft GitHub CI must complete the source build,
identity assertions and unchanged live storage tests before runtime acceptance.
Preserve the blocked local attempt and the remote provenance/report separately.
Reverting this CI-only slice does not affect user databases or product images;
it restores the currently unavailable registry dependency.
