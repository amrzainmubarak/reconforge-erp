# ADR 0114: Operator-keyed local backup envelopes

- Status: Accepted
- Date: 2026-07-27

## Context

The existing Community SQLite backup is a bounded, checksum-verified pair of
JSON files. It intentionally includes credential verifier material required by
restore, so a copied backup can disclose sensitive persisted data. A checksum
detects accidental change but does not authenticate ciphertext or hide content.

## Decision

Add an optional `backup` dependency profile pinned to cryptography 50.0.0 and
wrap the existing versioned backup pair in one AES-256-GCM envelope. The
operator supplies an exact 32-byte key through a local key file; keys are never
accepted as CLI values, stored in the envelope, or logged. The envelope binds
its format with associated data, authenticates before any target mutation, is
resource-bounded and duplicate-safe, and publishes through an exclusive
staging file plus atomic file replacement. The plaintext backup format remains
readable for compatibility.

## Consequences

Community operators gain confidentiality and authenticated integrity without a
network service or mandatory dependency. A key fingerprint helps identify the
required key but is not authorization or key escrow. Decrypt/restore uses a
short-lived operating-system temporary directory, so operators must protect the
temporary volume and securely manage key generation, separation, backup, and
rotation. This slice does not prove PostgreSQL backup, centralized restore
authorization, external key management, host-loss durability, or a complete DR
matrix; P1-PLAT-010 remains open.

## Reversibility

Remove the optional commands and dependency while retaining the unchanged
plaintext reader. Existing `.rfbackup` files require this reader and their
operator-owned keys; never silently downgrade them to unauthenticated input.
