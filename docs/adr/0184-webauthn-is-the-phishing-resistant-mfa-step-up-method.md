# ADR 0184: WebAuthn is the phishing-resistant MFA step-up method

Date: 2026-07-29

Status: Accepted

## Context

Password reauthentication is useful session assurance but is still the same
factor used for local login. Shared-secret OTP would introduce recoverable MFA
secrets at rest and remains phishable. Privileged deployments need a distinct,
origin-bound possession factor without custom cryptography.

## Decision

- Use the W3C WebAuthn ceremony through the pinned `webauthn==3.0.0` library.
  ReconForge does not implement signature or attestation cryptography itself.
- WebAuthn is disabled unless an operator supplies a closed, versioned JSON
  configuration with an RP ID, display name, and one to eight exact origins.
  Non-loopback origins require HTTPS and must equal or be below the RP ID.
- Registration requires an authenticated human and recent password or existing
  WebAuthn step-up. Registration and authentication require authenticator user
  verification.
- Server-generated 256-bit challenges last five minutes, are bound to tenant,
  user, session, and ceremony, and are consumed in a committed transaction
  before response verification so failed verification cannot replay them.
- Store only credential ID, COSE public key, signature counter, bounded
  transports, device/backup metadata, and a label. No authenticator private key
  or shared MFA secret is stored.
- Successful authentication updates the counter under optimistic concurrency
  and appends a ten-minute `webauthn_user_verified` assertion bound to the
  current revocable session.
- When WebAuthn configuration is enabled, every permission in the closed
  privileged registry requires `webauthn_user_verified`; password-only step-up
  returns `mfa_required`. Community/SQLite remains unchanged.

## Consequences

This is evidence-bounded WebAuthn MFA support for the PostgreSQL server profile.
It is not proof of every browser/authenticator combination, account recovery,
attestation policy, hosted IdP interoperability, production deployment, or
independent assurance.

## Rollback

Migration 0040 can downgrade to 0039 after deleting only WebAuthn step-up
assertions with the append-only trigger temporarily disabled inside the
migration transaction. Credential/evidence retention approval remains required
before a real deployment rollback.

## References

- W3C Web Authentication Level 3: https://www.w3.org/TR/webauthn-3/
- py_webauthn documentation: https://duo-labs.github.io/py_webauthn/
