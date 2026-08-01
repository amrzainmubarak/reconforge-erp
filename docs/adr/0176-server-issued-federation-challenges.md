# ADR 0176: Server-issued one-time federation challenges

- Status: Accepted
- Date: 2026-07-28

## Context

Cryptographic verification of an OIDC nonce or SAML `InResponseTo` is not sufficient when the caller supplies both the assertion and the expected correlation value. ReconForge must prove that the expected value originated at its own tenant boundary and was not replayed.

## Decision

Add a public, tenant-required `POST /api/v1/auth/federation/challenge` operation. PostgreSQL generates a random opaque challenge plus protocol-specific OIDC nonce or SAML request ID, persists only SHA-256 hashes under forced RLS, and expires it after five minutes. Login requires the opaque challenge and returned correlation value; one atomic update consumes the exact tenant/provider/protocol/hash tuple before assertion verification. Challenges are serialized per tenant/provider, expired or consumed rows are pruned, and at most 100 active challenges may exist for one provider.

## Consequences

- Client-selected nonce and request-correlation values no longer authorize login.
- Failed verification burns the challenge; clients must initiate again.
- Exact assertion replay is denied by the consumed challenge and the independent assertion replay table.
- The endpoint returns public correlation material only; no provider secret, private key, assertion, subject, group, or session token is stored in the challenge table.

## Rollback

Remove both public federation routes together. Do not restore direct assertion login without a server-issued challenge. Migration 0034 can remove the challenge table only as part of full federation rollback after required audit retention.
