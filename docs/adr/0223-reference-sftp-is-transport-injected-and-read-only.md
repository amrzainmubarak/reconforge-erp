# ADR 0223: Reference SFTP is transport-injected and read-only

- Status: accepted
- Date: 2026-08-02

## Decision

Add a synthetic `reference-sftp-readonly` connector with an exact allowlisted
SFTP endpoint, runtime secret reference, traversal-free root, bounded file
count/size, extension allowlist, deterministic ordering, cursor, and content
digests. The connector depends on a `SftpTransport` protocol rather than
bundling an SSH implementation or making network calls in the repository.

`NetworkConnectorRegistration` remains HTTPS-only; SFTP has its own closed
registration so an SFTP URL cannot accidentally reach the HTTPS executor.

## Consequences

- SFTP path, replay, size, and credential-isolation behavior is executable with
  synthetic transports and no external account.
- Host-key verification, SSH algorithm policy, provider availability, and live
  operational evidence remain explicit adapter responsibilities.
- The connector is read-only; no write-back, payment, or ERP mutation exists.

## Rollback

Remove the SFTP module, tests, docs, ADR, exports, and manifest changes. No
database or external state is changed.
