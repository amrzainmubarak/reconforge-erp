# ADR 0768: Close the local exact container scan with a fresh Grype database

- **Status**: Accepted for the local candidate evidence
- **Date**: 2026-08-28
- **Scope**: Local image security evidence; hosted release remains separately gated

## Context

The Python 3.12 candidate had passed Docker Scout and the application matrix,
but the release-integrated Syft/Grype gate could not be called complete while
the local Grype database was older than the policy's 120-hour limit. A previous
refresh attempt stalled during download. The correct response is to obtain the
official database through Grype, import it into an isolated cache, verify its
native status, and run the exact subject-bound scan without weakening age,
severity, VEX, license, or source-binding rules.

## Decision

Use the official Grype 0.117.0 database update/import path in a disposable
cache. The imported database is schema `v6.1.9`, built at
`2026-08-28T09:21:39Z`, and its verified SQLite payload SHA-256 is
`4304a9eb9165b8ffd0613b0b60b0379444e1a9b5ef0882ca80547775f3bef054`.
Disable automatic refresh only after `grype db status` reports the imported
database valid; this makes the scan deterministic and prevents a second
network call from silently changing the subject during validation.

## Evidence

- Syft 1.51.0 generated the candidate native SBOM from the linux/amd64 image.
- Grype 0.117.0 scanned that SBOM with the hash-bound OpenVEX document and
  exited 0: 16 active matches and 3 VEX-ignored fixed matches.
- The repository validator returned `status=passed`, zero blockers, and zero
  active exceptions. It recorded 68 packages, 94.11% license metadata
  coverage, and three exact Python 3.12.14 fixed High dispositions.
- The evidence artifact is
  `docs/execution/CONTAINER_SECURITY_LOCAL_2026-08-28.json`, bound to image
  config `sha256:08723531122c50615c42860fd299b9bb797ba67c231b7f1cb5b1cc8b3822cf0f`
  and manifest `sha256:3ddcdc5dc7636350f5919c6915a935940dac322e07483a7ffe01473fa7facf1b`.

## Boundary

This closes the local exact scanner disposition for the candidate. It does not
prove hosted clean-build reproducibility, registry publication, signed
provenance, legal license compatibility, vulnerability reachability, or
production security effectiveness. The retained high findings remain visible
in counts; only the three exact source-proven fixed dispositions are governed
by OpenVEX. No severity override or broad ignore is permitted.
