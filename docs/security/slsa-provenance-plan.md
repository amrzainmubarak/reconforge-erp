# SLSA 1.2 Provenance Plan

The normative source is `docs/security/slsa-provenance-plan.v1.yaml`, validated
by `docs/schemas/slsa_provenance_plan.schema.json`. It is an implementation
plan, not generated provenance, not a builder assessment, and not a SLSA level
or verified-property claim.

## Specification boundary

- Current Approved specification: SLSA 1.2, announced 2025-11-24.
- Official specification: <https://slsa.dev/spec/v1.2/>
- Official announcement:
  <https://slsa.dev/blog/2025/11/announce-slsa-v1.2>
- Official repository: <https://github.com/slsa-framework/slsa>
- Pinned tag `v1.2`: commit
  `19e4e2f005f871270c4f555fc47afecfb37f3efe`.
- Observed `releases/v1.2` branch head on 2026-07-25:
  `ae7fc76215004e8fae250c877eff8919bf048e3b`; the tag is the immutable plan
  source while the branch identity is recorded separately.
- Tracks covered by the specification: Build and Source.

ReconForge currently records `SLSA_BUILD_LEVEL_UNEVALUATED` and
`SLSA_SOURCE_LEVEL_UNEVALUATED`, with no verified properties. A workflow
definition or successful build does not change that result.

## Artifact identities

| ID | Required immutable identity | Current evidence ceiling |
| --- | --- | --- |
| `source-archive` | Exact filename/version, SHA-256 subject, immutable source revision, matching package/npm metadata | Deterministic clean-HEAD local archive/SBOM plus candidate definition; no hosted attestation result |
| `python-wheel` | Exact filename/version, SHA-256 subject, source revision, build definition | Candidate workflow definition; no hosted attestation result |
| `python-sdist` | Exact filename/version, SHA-256 subject, same source revision as wheel | Candidate workflow definition; no hosted attestation result |
| `container-image` | Registry repository plus manifest digest; Dockerfile/base/source/builder binding | Exact local configuration-bound image scan records three source-proven fixed CPython High matches and blocks on two OpenSSL High matches; no registry/attestation result |
| `cyclonedx-sbom` | One exact file/digest per source/wheel/sdist/image subject, covered digest, generator/dependency/release binding | Deterministic local source/package outputs plus an exact local Syft image inventory; no hosted image predicate or attestation result |

All release subjects must be path-free and digest-addressed. Mutable tags are
discovery aids, never sole identity. Package, image, SBOM, source revision, and
release-tag versions must agree.

## Trust boundaries

| ID | Boundary | Current state |
| --- | --- | --- |
| `source-control` | Git revision/tag, rulesets, history, privileged repository access | Partial; external enforcement unverified |
| `tenant-build-definition` | Repository workflows, Dockerfile, build config, public parameters | Partial; tenant-controlled and cannot self-attest trust |
| `hosted-control-plane` | Orchestration, provenance generation, immutable builder identity | Planned |
| `build-environment` | Runner isolation, dependencies, caches, secrets, cross-run influence | Partial; candidate pins tools and disables build cache, hosted controls unassessed |
| `attestation-signing` | Issuer/subject identity, keyless or standard signing, revocation | Partial; keyless workflow definition only, no retained hosted result |
| `distribution` | Atomic artifact/attestation/SBOM publication and retention | Partial; short-lived candidate bundle only, no release/SBOM/PyPI coupling |
| `consumer-verification` | Independent expectations, verifier, failure and offline boundaries | Partial; strict commands/runbook exist, no independent retained run |

Provenance generation and signing must be outside tenant-defined build steps.
No long-lived signing secret may be stored in the repository or exposed to
those steps.

## Attestation contract

- Statement type: `https://in-toto.io/Statement/v1`.
- Predicate type: `https://slsa.dev/provenance/v1`.
- Every subject has an exact name and SHA-256 digest.
- `buildDefinition` binds the versioned build type, release tag, source URI and
  full revision, artifact set, workflow/build identity, actions, base image,
  build tools, and locked inputs.
- `runDetails` binds the allowlisted builder, unique invocation, UTC start/end,
  and safe byproduct digests.
- Signature verification binds issuer and subject to the repository, immutable
  workflow/ref, and builder. Verification evidence records verifier version and
  independent policy digest.
- Secrets, customer data, private paths, mutable dependencies, and self-asserted
  levels/properties are prohibited.

## Verification and failure

The only permitted release ref type is `signed-release-tag`. Verification must
strictly parse the statement, authenticate it, recompute subject digests, and
compare source, tag, workflow, builder, build type, parameters, dependencies,
versions, and policy digest against independent expectations.

Missing, malformed, unsupported, unauthentic, mismatched, revoked, or
unexpected evidence blocks publication or promotion and quarantines the
artifact/attestation pair. A repeated run with unchanged inputs is not a fix.
Safe failure records retain the artifact digest, correlation ID, verifier
version, and policy digest without secrets or customer data.

## Rollback contract

Rollback never overwrites an artifact, tag, provenance statement, signature,
or verification record. It stops promotion, preserves evidence, marks affected
digests revoked/deprecated, removes mutable discovery references when needed,
rotates compromised identities, rebuilds from a reviewed immutable revision,
reverifies, and publishes replacement/advisory lineage from affected to
replacement digests.

## Implementation gates

| Gate | Outcome | Status |
| --- | --- | --- |
| `PROV-G01` | Immutable clean source/tag identity and version checks | Partial |
| `PROV-G02` | Immutable workflow/build/action/base/tool/dependency identity | Partial |
| `PROV-G03` | Deterministic artifact name/media/version/digest subjects, with bounded same-machine source/wheel/normalized-sdist byte parity | Partial |
| `PROV-G04` | Trusted control-plane provenance generation | Partial |
| `PROV-G05` | Builder control-plane/isolation assessment | Planned |
| `PROV-G06` | Keyless/standard attestation authenticity and compromise paths | Partial |
| `PROV-G07` | Coupled artifact/provenance/SBOM distribution | Partial |
| `PROV-G08` | Independent verifier, policy, golden and negative fixtures | Partial |
| `PROV-G09` | Fail-closed release enforcement and governed exceptions | Partial |
| `PROV-G10` | Synthetic revocation/replacement/rollback drill | Planned |
| `PROV-G11` | Branch-specific Source Track controls and continuity assessment | Planned |
| `PROV-G12` | Artifact-specific claim/evidence review and expiry | Planned |

Eight gates are partial: the repository now defines clean signed-tag checks,
hash-locked release and container-scanner tools, commit-epoch package normalization, exact artifact
manifests, GitHub keyless provenance, strict bundle verification, and
fail-before-registry-authentication container policy, fail-before-candidate-upload behavior,
and one exact-subject CycloneDX 1.7 generation/attestation set. The exact local
image scan records three source-proven fixed CPython matches and remains blocked
by two OpenSSL High matches. Two local Python 3.14.6 builds reproduced
identical source, wheel, and normalized-sdist bytes; this does not cover the OCI
image, supported-version runners, another platform, or a clean tag. No
hosted run, signed output, retained verification, builder assessment, coupled
release/SBOM publication, rollback drill, Source Track assessment, or level
review is proven; the other four gates remain planned.

## Review and allowed wording

Review is owned by `release-security` every 90 days, next due 2026-10-23, and
earlier on SLSA spec/format, builder, source-control, signer, verifier, registry,
workflow, incident, or proposed level/property changes.

Allowed wording: “ReconForge maintains a version-pinned SLSA 1.2 provenance
implementation plan; Build and Source tracks are unevaluated.” Do not claim a
Build/Source level, verified property, signed release, trusted builder,
conformance, compliance, certification, or production readiness until the
artifact-specific gates and independent evidence pass.
