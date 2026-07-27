# ADR 0067: Gate Publication Behind Tag-Only Signed Release Candidates

- Status: Accepted
- Date: 2026-07-25

## Context

The versioned SLSA plan defines artifact identities and fail-closed verifier
expectations, but existing workflows neither build one release set nor create
or verify signed provenance. Directly automating GitHub Release or PyPI
publication would add irreversible external effects before repository release
immutability, environment approval, and remote execution were evidenced.

## Decision

Add a tag-only, non-publishing candidate workflow. It requires an exact signed
annotated version tag, clean upstream-main source, hash-locked Python build
  tools, full-SHA action pins, exact source/wheel/sdist/image identities, GitHub
  commit-time `SOURCE_DATE_EPOCH`, fail-closed deterministic sdist normalization,
  keyless SLSA provenance, preserved Sigstore bundles, and independent
repository/workflow/ref/revision/runner verification before a short-retention
Actions artifact is uploaded.

The workflow may push an image under a commit-specific candidate tag because
OCI provenance verification requires a registry subject. The image is governed
by its manifest digest; the mutable tag is never sufficient identity. GitHub
Release and PyPI publication are explicitly absent and remain separately
authorized human gates.

## Consequences

- A tag push can exercise signing and registry writes only after the configured
  `release-candidate` environment gate; it cannot create a GitHub Release.
- The workflow definition and local tests are not remote attestation evidence.
- GitHub-hosted runner, OIDC, repository rules, environment reviewers, GHCR,
  transparency, and revocation remain external controls requiring assessment.
- A release-manifest helper rejects version, package metadata, archive path,
  source-epoch, digest, artifact-set, and image-repository drift before
  attestation. The normalizer rejects paths outside the package root, links,
  special members, and duplicates without overwriting the input on rejection.
- Two same-machine Python 3.14.6 builds with epoch `1784876463` reproduced
  identical source, wheel, and normalized-sdist bytes. This is bounded local
  package evidence, not clean hosted, cross-platform, image, or SLSA evidence.
- P0-SEC-006 remains in progress until a reviewed clean-tag run and independent
  verification exist. P0-SEC-007 remains responsible for per-artifact SBOMs.

## Reversibility

Disable the workflow or candidate environment without publishing a release.
Preserve any generated artifacts, bundles, run IDs, and exact digests. Never
overwrite a signed tag or published artifact; use a new version after a failed
or compromised candidate.
