# SSO/OIDC/SAML Design Only

Status: roadmap design only. Not implemented.

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

Tests required before implementation:

- Invalid issuer/audience rejection.
- Role mapping limits.
- Local fallback behavior.
- No secret export/log leakage.

Not supported today:

- OIDC login.
- SAML login.
- SSO provisioning.
