# Browser administration session boundary

## Scope

`POST /api/v1/auth/browser/login` is for a same-origin HTTPS browser client.
It accepts the normal closed username/password body and returns only:

```json
{"csrf_token":"...","expires_at":"..."}
```

The response also sets `__Host-reconforge_session` as an `HttpOnly`, `Secure`,
`SameSite=Strict`, host-only cookie. It deliberately does not serialize an
`access_token`. Do not copy an API bearer token into a Vite variable, HTML,
browser storage, a query string, a test fixture, or support logs.

## Request behavior

- Safe cookie-authenticated requests can use the session cookie alone.
- Every unsafe cookie-authenticated request must send the current
  `X-ReconForge-CSRF` proof returned by browser login. The proof is bound to
  the session and an old proof fails after a different session is issued.
- An explicit `Authorization: Bearer` header remains the compatibility path
  for API/CLI clients and takes precedence if both transports are presented.
- `POST /api/v1/auth/logout` revokes a browser session and clears its cookie
  when the cookie transport was used. It requires the CSRF proof in that mode.

## Operator and UI requirements

1. Serve the UI and API on the same HTTPS origin; do not enable cross-origin
   credential sharing to make this boundary work.
2. Keep the returned CSRF proof in component memory only and discard it on
   logout, session failure, route reload that loses session context, and user
   switch. It is not a bearer credential, but persistent storage is not needed.
3. When an administration request returns `401`, clear local UI state and show
   a sign-in path. When it returns `403 csrf_required`, stop the mutation and
   require a fresh browser-session flow. When it returns `403 step_up_required`
   or `mfa_required`, show the configured human step-up flow; never retry a
   privileged operation silently.
4. Treat every response as a closed disclosure contract. Administration views
   may render only fields returned by their documented redacted/count-only API
   models; they must not construct missing identity, audit, retention, or
   secret data client-side.

## Limits

This boundary does not itself serve static assets, configure CSP, provide a
browser login or WebAuthn screen, prove reverse-proxy cookie behavior, cover
all assistive technologies, or establish compliance/certification/Enterprise
readiness. The existing bearer API remains supported.
