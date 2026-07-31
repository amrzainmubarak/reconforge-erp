# ADR 0172: Static-JWKS OIDC verification

## Status

Accepted — 2026-07-28

## Context

OIDC ID Tokens require JOSE signature and claim verification. Dynamic discovery
and token-controlled key URLs introduce network, SSRF, key-substitution and
availability boundaries. ReconForge must not implement JOSE or accept an
algorithm selected solely by the token.

## Decision

Use locked `joserfc` 1.7.4 for OIDC cryptography. The adapter accepts only an
operator-supplied bounded public JWKS per configured provider. It rejects private
key material, missing or duplicate `kid`, and any `jku` or `x5u` header. Decoding
receives the provider algorithm allowlist. Claims require exact issuer, subject,
allowed audience, expiry, issued-at and expected nonce; multiple audiences require
an allowed `azp`. SHA-256 of the authenticated compact token is its replay identity.

## Consequences

Real RSA-signed OIDC verification is executable without network discovery or
home-grown JOSE. JWKS rotation is explicit and old/new keys may coexist within
the 32-key bound. Discovery, SAML, durable replay/link/session storage, logout and
API routes remain; P3-ENT-001 is not complete.
