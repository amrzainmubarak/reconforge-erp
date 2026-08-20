# ADR 0257: Write-back intents are append-only before provider I/O

## Decision

Governed write-back intents are persisted locally as an append-only version history. Each version stores only the digest-bound intent contract, tenant/workspace scope, status, and canonical JSON; payload contents and credentials are not stored. Idempotent replay of an identical digest returns the existing version. Any new version requires the expected current version and an allowed lifecycle transition.

The repository performs no network I/O and does not make a provider integration live. Provider dispatch remains behind the existing approval, idempotency, acknowledgement, and compensation boundary.

## Rationale

Durable intent history is required to reconcile retries and operator review without making an external mutation invisible or mutable in place.
