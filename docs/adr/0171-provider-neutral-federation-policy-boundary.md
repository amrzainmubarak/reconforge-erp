# ADR 0171: Provider-neutral federation policy boundary

## Status

Accepted — 2026-07-28

## Context

Enterprise federation must support OIDC and SAML without implementing JOSE,
XML Signature, discovery, or protocol parsing inside ReconForge. Verification
libraries alone do not own tenant role allowlists, replay persistence, local
session linkage, audit semantics, or sovereign deployment policy.

## Decision

Introduce a typed Federation Application boundary. Reviewed adapters own all
cryptographic and protocol parsing and return a closed verified-assertion model.
ReconForge independently checks exact protocol, issuer, audience, configured
algorithm, signature-verification state, issued/not-before/expiry times, OIDC
nonce or SAML request correlation, one-time assertion identity, and role mapping.
Only configured external groups may map to configured local roles. Audit records
contain provider ID, outcome, and safe reason code—never tokens or claims.
Network-required federation fails closed in air-gap mode.

## Consequences

The policy and verification boundary is executable and hostile-tested without
creating home-grown cryptography. The process-local replay store is explicitly
non-enterprise; PostgreSQL replay/link/session persistence remains required.
P3-ENT-001 cannot close until real OIDC and SAML library adapters validate signed
fixtures, logout and route/session behavior pass, and dependencies are locked and
audited.
