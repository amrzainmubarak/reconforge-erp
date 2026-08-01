# SSO/OIDC/SAML Federation Boundary

Status: bounded implementation complete for P3-ENT-001. The provider-neutral
policy, static-JWKS OIDC and signed-Response SAML adapters, operator JSON loader,
server-issued one-time challenge, durable replay/link/session/audit storage,
HTTP login and existing session logout are implemented and locally/live tested.
This is not hosted production evidence, IdP interoperability certification, or
enterprise readiness. Authenticated SCIM and WebAuthn MFA are now separate
bounded implementations and do not widen this federation claim.

Architecture direction:

- Keep local users as fallback.
- Add optional OIDC/SAML authentication providers through explicit local configuration.
- Map external identities to local users and roles.
- Store no raw identity-provider secrets in exports.
- Keep sessions in the existing hashed local session table.

Security risks:

- Misconfigured role mapping can over-grant access.
- Public callback URLs change deployment boundaries.
- Logout semantics vary by provider.

Verified contracts:

- Invalid issuer/audience rejection.
- Role mapping limits.
- Local fallback behavior.
- No raw assertion, subject, issuer, group, token, nonce, or SAML request ID persistence in federation storage.

Not supported yet:

- Authorization-code exchange, dynamic discovery, token-directed key retrieval, or IdP-initiated SAML.
- Provider single logout or an administration UI. SCIM and WebAuthn step-up are separate bounded surfaces.
- Hosted cross-version/interoperability evidence or external security review.

Implemented boundary:

- Closed provider configuration with issuer, audience, algorithm, role and group allowlists.
- Library-owned verification port; ReconForge does not parse or verify JWT/XML itself.
- Exact issuer/audience/protocol/algorithm checks after adapter verification.
- OIDC nonce and SAML request-correlation enforcement.
- Expiry, issued-at and not-before checks with bounded clock skew.
- One-time assertion replay contract and sanitized audit outcomes.
- Deny-by-default role mapping and network federation disabled in air-gap mode.
- OIDC ID Tokens use locked `joserfc`, real signature verification, static
  operator-owned public JWKS, algorithm allowlists, required claims,
  multi-audience `azp`, and reject token-controlled key URLs.
- SAML Responses use locked python3-saml/xmlsec, fixed IdP certificates, strict
  message signature validation, one Assertion, request/destination/recipient,
  issuer/audience/time checks, and explicit signature/digest allowlists.
- A bounded versioned JSON configuration accepts public JWKS and public IdP
  certificates only and is wired to `reconforge api serve` through
  `--federation-config` / `RECONFORGE_FEDERATION_CONFIG`.
- The server issues a five-minute, one-time OIDC nonce or SAML request ID,
  persists hashes only under forced RLS, caps active challenges per
  tenant/provider, and consumes the challenge before assertion verification.
- Successful assertions bind only to pre-provisioned active local users and
  cannot widen their existing local roles. The existing hash-only PostgreSQL
  session and `/api/v1/auth/logout` own revocation.
