# ADR 0068: Bind CycloneDX SBOMs to Each Release Subject

- Status: Accepted
- Date: 2026-07-26
- Owners: Release Security, Security Architecture
- Backlog: `P0-SEC-007`

## Context

The former `sbom.yml` installed an unpinned `cyclonedx-bom`, inspected the
GitHub runner environment, emitted one CycloneDX 1.6 document, and ran
separately from the release build. That output could neither identify which
source archive, wheel, sdist, or OCI manifest it covered nor prove that its
dependency set came from those subjects. It also created a second tag-triggered
path that could drift independently from the candidate workflow.

Artifact-specific SBOMs need exact subject digests, deterministic serialization,
generator identities, explicit completeness, and the same source/tag/workflow
expectations as provenance. A declared Python requirement is not an installed
transitive package, a package-lock entry is not proof of runtime reachability,
and a repository workflow definition is not evidence that an image scan or
attestation ran.

## Decision

Use CycloneDX JSON 1.7 with predicate type `https://cyclonedx.org/bom`, and
generate one SBOM for each candidate subject in the existing tag-only release
job:

1. The source-archive SBOM reads `pyproject.toml` without extraction, verifies
   exact metadata parity with wheel `METADATA` and sdist `PKG-INFO`, records
   unresolved declared Python constraints, and inventories resolved versions
   from the matching `apps/web/package-lock.json` when present.
2. The wheel and sdist SBOMs record the same declared Python constraints, but
   bind different exact artifact names and SHA-256 values. They do not pretend
   that lower bounds or extras are resolved transitive inventories.
3. The image SBOM comes from Syft 1.49.0 scanning the exact
   `ghcr.io/amrzainmubarak/reconforge-erp@sha256:<digest>` subject. The workflow
   downloads the official Linux AMD64 archive over HTTPS, checks published
   SHA-256 `7aa2f03ee92739cf643279ba3990548b9925d4e22cae13f46831ee62821147fe`,
   and verifies version, commit
   `29fd7d0dec81cf03e0a1194a1985c7c893bb2396`, and platform before use.
4. A bounded normalizer replaces only volatile document/subject metadata,
   preserves and canonically orders the observed inventory, rejects duplicate or
   unknown references, signatures it would invalidate, unsupported formats or
   tools, pre-injected policy fields, and configured host-path disclosures.
5. `sbom-manifest.v1.json` binds the release-manifest digest, four subject and
   SBOM digests, generator identities, component counts, canonical inventory
   digests, generation modes, verification requirements, and `unknown`
   completeness. `SBOM_SHA256SUMS` covers all four SBOMs and the manifest;
   outputs use exclusive temporary creation followed by atomic replacement.
6. Four separate `actions/attest@v4` calls bind each CycloneDX predicate to its
   exact file or OCI subject. The same job preserves each bundle and verifies
   predicate type, repository, workflow, workflow/source revision, tag ref, and
   GitHub-hosted runner expectation before candidate upload.
7. Remove the independent legacy SBOM workflow. Keep Docker BuildKit automatic
   `sbom` disabled because the reviewed per-subject scan and attestation path is
   explicit. Keep GitHub Release and PyPI publication outside this workflow.

## Consequences

- Identical inputs, source epoch, generator policy, and synthetic Syft inventory
  produce identical SBOM bytes; exact subject digests intentionally produce
  different subject documents.
- Source npm inventory can disclose locked versions even when some lock entries
  lack integrity values. Missing hashes remain visible through omission and the
  whole document remains `unknown` completeness.
- The release fails before attestation when source/package declarations drift,
  a file digest changes, npm root metadata disagrees, the image scan is empty or
  malformed, or a forbidden host path appears.
- This does not establish dependency safety, vulnerability absence, license
  clearance, runtime reachability, complete transitive coverage, a signed
  release, a trusted builder, immutable publication, or any SLSA level.
- Docker is unavailable in the local environment, so the image document has
  only deterministic fixture coverage until a reviewed hosted digest scan runs.

## Compatibility and rollback

No runtime Python, API, CLI, database, or browser contract changes. The SBOM
manifest is a new schema-v1 candidate artifact. Release publication remains
absent.

To roll back safely, disable candidate creation rather than restoring the
floating environment workflow or bypassing verification. Preserve any artifact,
SBOM, manifest, checksum, bundle, and failure record already produced. Never
overwrite an SBOM for an existing subject digest; use a reviewed generator-policy
successor and new attestation when correction is necessary.

## Verification

- `tests/test_release_sbom_pipeline.py` covers deterministic output, exact
  subject hashes, source/wheel/sdist metadata parity, npm lock inventory,
  duplicate references, host-path disclosure, digest/manifest tampering,
  pre-existing temporary-file collision, schema identity, pinned scanner
  installation, per-subject attestation, and strict verification.
- Generated local fixtures validate against the official CycloneDX 1.7 JSON
  Schema as well as the repository SBOM-manifest schema.
- `actionlint` validates the integrated release workflow.

## Authoritative references

- <https://cyclonedx.org/specification/overview/>
- <https://cyclonedx.org/schema/bom-1.7.schema.json>
- <https://github.com/anchore/syft/releases/tag/v1.49.0>
- <https://github.com/actions/attest>
- <https://cli.github.com/manual/gh_attestation_verify>
