# ADR-0516: Close the Gitleaks history and checked-tree scan without broad ignores

## Status

Accepted — local evidence only; hosted security attestation remains external.

## Context

The current checked tree and complete local Git history must be scanned with the
same configured Gitleaks rules before a release decision. The replay-fence
documentation used wording that the generic-api-key rule classified as a
credential-like phrase. The wording was neutralized in the current tree; the
already immutable historical commit is handled with exact commit/path/rule/line
fingerprints only.

## Decision

Keep `.gitleaks.toml` on the default rules and add only the two exact historical
fingerprints reported by Gitleaks 8.30.1. Do not add a broad path, commit-range,
regex, or rule exclusion. Record both the checked-tree and `--all` history
scans, including the archive checksum, as local evidence.

## Verification

On 2026-08-11, Windows x64 Gitleaks 8.30.1 archive SHA-256 was
`d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`.
`gitleaks dir --config .gitleaks.toml` scanned 30.86 MB and exited 0 with no
leaks; `gitleaks git --config .gitleaks.toml --log-opts=--all` scanned 708
commits / 24.21 MB and exited 0 with no leaks.

## Boundary and rollback

This is workstation evidence, not a hosted GitHub security result or a claim
about credentials outside the repository. Revert this ADR, the two exact
fingerprints, and the neutral wording together if the scan policy changes.
