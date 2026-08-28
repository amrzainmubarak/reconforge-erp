# ADR 0613: PostgreSQL worker strategy parity profile

Status: Accepted

## Decision

Add a bounded provider-neutral profile that compares the direct grouped and
sequential strategy result digest with the digest carried by the PostgreSQL
worker projection lineage. It covers five grouped modes and three sequential
modes, rejects missing or multiple projected digests, and records one stable
profile digest.

The profile runs in process without a PostgreSQL connection. It proves worker
adapter projection parity only; live PostgreSQL execution, transaction
behavior, crash recovery, and capacity remain separate gates.
