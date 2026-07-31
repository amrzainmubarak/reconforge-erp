# ADR 0199: Browser administration sessions are same-origin and CSRF-bound

## Status

Accepted on 2026-07-30.

## Context

The PostgreSQL administration APIs require a human bearer session and current
privileged assurance. The static Studio client must not be given a bearer value
through a build variable, URL, fixture, or persistent browser storage merely
to render those views. Doing so would make an administrator credential
available to scripts, browser history, bundles, or accidental diagnostics.

## Decision

- Keep the existing `POST /api/v1/auth/login` bearer response unchanged for
  API/CLI compatibility.
- Add `POST /api/v1/auth/browser/login` for same-origin browser use. It emits
  no bearer token in JSON; it sets only the host-only
  `__Host-reconforge_session` cookie with `HttpOnly`, `Secure`, `Path=/`, and
  `SameSite=Strict` attributes.
- The browser login response exposes a bounded CSRF proof, not the session
  credential. The proof is an HMAC-SHA-256 of a random nonce under the current
  session token, so it cannot validate after a different session is issued.
- Authentication accepts either the explicit Bearer header or the browser
  cookie. Unsafe cookie-authenticated requests must carry the exact
  `X-ReconForge-CSRF` proof. Bearer clients retain their existing API behavior;
  an explicit bearer takes precedence when both transports are supplied.
- Browser logout revokes the session and clears the cookie. A bearer logout
  does not clear an unrelated browser cookie.

## Consequences

- A same-origin UI can hold only the short-lived CSRF proof in memory while
  the bearer credential remains inaccessible to browser JavaScript.
- The API remains default-secure: a browser session requires HTTPS-compatible
  cookie delivery, and unsafe cookie requests fail closed without a proof.
- This is an authentication transport boundary, not a complete browser
  deployment. A production UI still needs a same-origin hosting topology,
  CSP and static-asset policy, an accessible login/step-up flow, WebAuthn UX
  where configured, mutation-specific CSRF tests, logout/session-expiry UI,
  and independent security review.

## Rollback

Remove `/api/v1/auth/browser/login` only after browser callers have migrated
to an approved replacement. Existing bearer login and sessions remain
compatible. Clearing the browser cookie alone is not a recovery action; the
server session must be revoked through the established logout/revocation path.
