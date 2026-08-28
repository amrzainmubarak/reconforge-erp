# ADR 0537: Fail closed before container registry authentication

- Status: Accepted
- Date: 2026-08-22
- Scope: E-823 exact-image supply-chain evidence and release publication boundary

## Context

The release candidate workflow generated an exact-subject CycloneDX image SBOM,
but it first authenticated to GHCR and pushed the candidate. It did not enforce
container vulnerability severity, scanner/database freshness, suppressed
findings, or license-inventory completeness. Converting the native Syft document
to CycloneDX also loses image/package context that a vulnerability scanner can
need for distro-aware matching. A later scan therefore could not serve as a
fail-before-external-write release control.

The exact image built on 2026-08-22 contains 68 observed package artifacts. A
checksum-verified Syft 1.51.0 inventory and Grype 0.117.0 database v6.1.9 scan
reported five High, twelve Medium, two Low, and one Negligible findings. Four
packages lacked usable license metadata, yielding 94.11% inventory coverage.
No independent VEX or approved exception exists.

## Decision

Build the Linux AMD64 candidate locally without registry credentials. Generate
both Syft native JSON and CycloneDX 1.7 from that local image, and scan the native
document with Grype. Validate all evidence with a repository-owned closed gate
that requires:

- exact policy-pinned scanner name, version, commit, platform, and archive hash;
- exact Syft configuration/manifest/platform/distro identity;
- an exact Grype source identity matching the Syft configuration and manifest;
- a valid supported Grype database no older than 120 hours at scan time;
- no suppressed matches and no operational scanner failure;
- at least 90% package-license inventory coverage;
- no Critical finding, no Unknown severity, and no High finding without an exact
  active container vulnerability exception.

Critical findings are never exceptable. License coverage is inventory evidence
only and does not assess legal compatibility or distribution rights. The gate
writes deterministic evidence for a policy block and returns a distinct blocked
exit code. It executes before `docker/login-action`. If it passes, the pushed OCI
manifest bytes must match the reported registry digest and reference the same
configuration digest that was scanned.

The weekly/manual security workflow repeats the same local-image gate. It is
skipped on ordinary push and pull-request events to avoid making every change pay
the image build cost; release tags always enforce it. Disposable PostgreSQL and
air-gap verification scripts also execute their reviewed external images by
digest while retaining historical tag labels in existing report schemas.

## Security and correctness

Native scanner input preserves source-image and distro context. Duplicate JSON
keys, symlink inputs, oversized input, unknown schema/tool identity, stale
database, ignored matches, subject mismatch, and incomplete finding identities
fail closed. Exceptions remain subject/advisory exact, time-bounded,
issue-backed, and separately approved by the existing policy. The current five
High findings intentionally block release; this ADR does not invent VEX or
reinterpret scanner output to make the gate green.

This decision affects release integrity and dependency evidence only. It changes
no financial amount, currency, matching rule, posting, audit record, tenant
boundary, or customer data path.

## Compatibility

CLI, API, database schemas, artifact formats, and runtime image behavior remain
unchanged. The image SBOM generator moves from Syft 1.49.0 to 1.51.0, so future
SBOM manifests identify the new reviewed generator. Historical SBOMs and ADR
0068 remain historical evidence and are not rewritten. A release candidate that
previously could reach GHCR before an image audit is now correctly blocked.

## Rollback

Reverting the gate is permitted only with a replacement that proves the same
pre-authentication subject binding, scanner/database integrity, vulnerability
and license-inventory policy, retained blocked evidence, and post-push
configuration binding. A temporary upstream advisory exception must use the
closed exception registry; it is not a rollback mechanism.
