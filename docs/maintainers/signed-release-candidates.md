# Signed Release Candidates

The tag-only `Signed Release Candidate` workflow builds and validates a bounded
candidate set. It does not publish a GitHub Release or PyPI package, and its
presence is not evidence that the workflow has run successfully.

## Enforced candidate boundary

The workflow accepts only a `vMAJOR.MINOR.PATCH` tag that exactly matches
`pyproject.toml`, resolves to the checked-out full revision, is contained in
`origin/main`, and is an annotated tag whose GitHub verification result is
`verified=true` with reason `valid`. The checkout must remain clean before any
build starts.

Before the first registry authentication, the same job validates the closed
supply-chain/exception contracts, checks `uv.lock` against `pyproject.toml`,
audits the hash-exported all-extra Python/server resolution, audits the npm lock,
and runs checksum-verified Gitleaks 8.30.1 over all Git history and the checked
tree with 100% redaction. It then builds the image without registry credentials,
generates subject-bound Syft native/CycloneDX inventories, scans the native
inventory with a current bounded Grype database, and enforces vulnerability and
license-inventory policy before the first GHCR login. Operational scanner errors fail closed. An active
exception must meet the exact subject, issue, ownership, two-approver, and expiry
contract; a critical npm finding cannot be excepted for release.

The candidate contains:

- a `git archive` source snapshot bound to the full revision;
- one pure-Python wheel and one sdist with matching package metadata; the
  commit timestamp is recorded as `SOURCE_DATE_EPOCH`, and the sdist is
  fail-closed normalized without filesystem extraction before hashing;
- one Linux AMD64 image pushed under a commit-specific candidate tag and
  identified only by its OCI manifest digest;
- a schema-v1 release manifest and deterministic SHA-256 checksum list;
- one subject-bound CycloneDX 1.7 SBOM for the source archive, wheel, sdist,
  and exact image manifest, plus a schema-v1 SBOM manifest and checksum list;
- separate Sigstore bundles for file/image provenance and each of the four SBOM
  predicates.

Build tools, uv/Gitleaks/Syft/Grype installers, and every action are pinned by exact
version/hash or full commit.
The image inventory scanner is Syft 1.51.0 at commit
`2293641e3bd628a01bb37639318d62c0ebe89b39`; the vulnerability scanner is Grype
0.117.0 at commit `b5fa92bbcbef655497e3be840a2f718380e2cdd3`. Their Linux AMD64 archives must
match the policy SHA-256 values before execution. The local scan is bound to the
image configuration digest, and the post-push registry manifest must reference
that same configuration before release metadata is created. Python package SBOMs describe declared,
unresolved constraints. The source SBOM additionally inventories versions from
the matching npm lock, and the image SBOM describes Syft-observed installed
components. All four declare `unknown` completeness.

The container gate rejects all Critical findings, High findings without an exact
active exception or reviewed fixed disposition, Unknown severities, ungoverned
ignored matches, stale or invalid databases, subject drift, and package-license
coverage below 90%. Fixed VEX is hash-bound, product-exact, 30-day reviewed,
and remains in total counts; no other VEX status is allowed. This coverage does
not establish license compatibility. The locally built 2026-08-22 image records
three source-proven fixed CPython matches and remains blocked by two OpenSSL
High matches; no release readiness follows from the workflow definition.

GitHub keyless attestations use SLSA provenance v1 or the CycloneDX predicate
type `https://cyclonedx.org/bom`, as applicable. The same job then verifies
each subject against the repository, workflow path, workflow/source revision,
tag ref, GitHub-hosted runner requirement, expected predicate type, and
preserved bundle. A failed check blocks candidate upload. The 14-day Actions
artifact is a review vehicle, not a release channel.

## Bounded local reproducibility evidence

On 2026-07-25, two consecutive dirty-worktree Python builds on Windows with
Python 3.14.6 and commit epoch `1784876463` produced identical wheel bytes
(`0bb308b4899d7dcd6721e72cca6b982ef43921b9436a30dfd4678aaefb47706b`).
After the release normalizer fixed gzip/tar time, owner, PAX-time, and member
ordering metadata, both sdists were also identical
(`b27e7e55f7befe46dba00c60e2fc1642c44dabf5be8a47c96e1693957cef5f45`).
Two `git archive` snapshots of `HEAD` matched at
`dc0404f9ecf7b60f31b4aa459791a69883f2a0a5fe512895b5d3dada5a3eae5f`.
This is same-machine, same-input evidence only. It does not cover the OCI
image, supported Python 3.11/3.12 runners, another operating system, a clean
release tree, or hosted GitHub execution.

## Required repository controls

Before a maintainer pushes a release tag, repository administrators must
configure the `release-candidate` environment with required reviewers and
tag-only deployment rules. They must also review GitHub-hosted runner,
source-control/ruleset, GHCR retention, privileged-access, incident, and
attestation-lifecycle controls. Workflow code cannot attest to those external
controls.

No long-lived signing key or package credential belongs in the repository.
The workflow uses the short-lived `GITHUB_TOKEN` and OIDC identity with only
`contents: read`, `packages: write`, `id-token: write`, and
`attestations: write` in its single job. It has no `contents: write`, PyPI token,
or release-publication step.

## Independent verification

Download the candidate files and bundles from the exact workflow run. Verify
checksums first, then use a current GitHub CLI with independent expected values:

```bash
sha256sum --check SHA256SUMS
sha256sum --check SBOM_SHA256SUMS
gh attestation verify reconforge_erp-X.Y.Z-py3-none-any.whl \
  --repo amrzainmubarak/reconforge-erp \
  --signer-workflow amrzainmubarak/reconforge-erp/.github/workflows/release.yml \
  --signer-digest FULL_RELEASE_SHA \
  --source-ref refs/tags/vX.Y.Z \
  --source-digest FULL_RELEASE_SHA \
  --deny-self-hosted-runners \
  --bundle files-provenance.sigstore.json
```

Verify every subject's SBOM with its own preserved bundle and explicit
CycloneDX predicate type. For example:

```bash
gh attestation verify reconforge_erp-X.Y.Z-py3-none-any.whl \
  --repo amrzainmubarak/reconforge-erp \
  --signer-workflow amrzainmubarak/reconforge-erp/.github/workflows/release.yml \
  --signer-digest FULL_RELEASE_SHA \
  --source-ref refs/tags/vX.Y.Z \
  --source-digest FULL_RELEASE_SHA \
  --deny-self-hosted-runners \
  --predicate-type https://cyclonedx.org/bom \
  --bundle wheel-sbom.sigstore.json
```

Repeat with the source, sdist, and digest-addressed OCI subject and their exact
SBOM bundles. Validate `sbom-manifest.v1.json` before interpreting component
counts. A missing version or integrity field remains missing evidence; do not
infer it from another environment.

Repeat for the source archive, sdist, release manifest, and checksum file. For
the image, use its exact manifest locator from `release-manifest.v1.json` and
the image bundle:

```bash
gh attestation verify oci://ghcr.io/amrzainmubarak/reconforge-erp@sha256:DIGEST \
  --repo amrzainmubarak/reconforge-erp \
  --signer-workflow amrzainmubarak/reconforge-erp/.github/workflows/release.yml \
  --signer-digest FULL_RELEASE_SHA \
  --source-ref refs/tags/vX.Y.Z \
  --source-digest FULL_RELEASE_SHA \
  --deny-self-hosted-runners \
  --bundle image-provenance.sigstore.json
```

For air-gapped verification, export a current trusted root and the bundles as
described by GitHub's official offline-verification procedure. Trusted roots
can rotate and revocation knowledge can become stale; record their retrieval
time and digest.

## Publication is a separate human gate

Do not automate publication from this candidate workflow. An authorized
maintainer must first enable GitHub immutable releases, review the exact
candidate/run/storage digest, create a draft release, attach every reviewed
asset, and only then publish it. After publication, run `gh release verify` and
`gh release verify-asset` for each local asset. PyPI publication requires its
own approved Trusted Publisher design and is outside this slice.

If any candidate or post-publication verification fails, stop promotion. Do not overwrite or delete evidence.
Do not move the signed tag, reuse an affected version, or weaken verifier expectations. Preserve the artifact/image digests, bundles,
policy inputs, run identity, and safe failure evidence; revoke or deprecate
discovery references and rebuild under a new reviewed version when required.

## Claim boundary

Static workflow tests and local manifest validation do not prove a clean hosted
run, signed tag, GitHub control operation, signature, provenance, registry
publication, immutable release, revocation drill, SBOM completeness, dependency
safety, license clearance, cross-platform or OCI-image reproducibility, or SLSA
Build/Source level. The local image SBOM tests use synthetic inventory because
Docker is unavailable. Both SLSA tracks remain UNEVALUATED; the bounded local
package/SBOM result above does not change that.
