# ADR 0206: Offline installation inputs are closed, local, and hash-locked

- Status: Accepted
- Date: 2026-07-30

## Decision

An air-gapped installation may consume only a closed manifest whose complete file
inventory uses normalized relative paths, exact byte sizes, and SHA-256 digests.
Python requirements must be exact-version, individually hashed records. The derived
installer command always uses `--no-index`, `--disable-pip-version-check`, and
`--require-hashes`; the manifest contains no commands or executable hooks. URLs,
path escapes, links, unexpected files, duplicate identities, and integrity drift fail
before an installer is invoked.

## Consequences

The verifier establishes local artifact integrity and a deterministic non-index
installer input. It does not download dependencies, execute installation, verify
Sigstore trust, prove OS/container isolation, or establish air-gapped readiness.
Those remain separate runtime gates in P3-ENT-011.

## Rollback

Reject and quarantine the bundle. Do not partially install it. Removing this contract
returns the Air-gap task to planned; it does not alter an installed deployment.
