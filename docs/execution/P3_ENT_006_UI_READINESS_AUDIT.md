# P3-ENT-006 Administration UI Readiness Audit

Date: 2026-07-30
Status: completed audit; no administration-browser implementation is claimed.

## Scope

This audit evaluates the shipped `apps/web` Studio shell as a potential host
for the PostgreSQL-only administration APIs introduced by E-190 through E-194.
It does not evaluate a deployed reverse proxy, identity provider, assistive
technology matrix, or an independently certified accessibility assessment.

## Passed evidence

| Gate | Result | Evidence |
| --- | --- | --- |
| Type safety | Passed | `npm --prefix apps/web run typecheck` completed successfully. |
| Component regression | Passed | `npm --prefix apps/web run test:run` passed 42 tests in 7 files. |
| Production bundle | Passed | `npm --prefix apps/web run build` completed successfully. |
| Browser regression | Passed | `npm --prefix apps/web run e2e` passed 10 Chromium tests, including automated Axe scans for the declared English/Arabic routes, keyboard focus restoration, reduced-motion/high-contrast preferences, path-redaction checks, and mobile landmarks. |

The existing Studio intentionally labels its local demo surfaces as synthetic.
Its only live-data page is read-only and fails closed when the authorized
metrics request fails; it never substitutes a synthetic result.

## Findings

1. The browser client has no server-session acquisition or privileged
   step-up flow. Current administration routes require an `Authorization:
   Bearer` token and central privileged assurance. Supplying a server token by
   build variable, local storage, URL, or a static fixture would disclose a
   credential and bypass the intended browser-authentication design.
2. No existing Studio route represents the disclosure contracts for identity,
   access, security-governance, or redacted audit administration. Adding a
   decorative page without a protected session would be a misleading shadow
   surface, not an administration UI.
3. The current automated accessibility evidence is meaningful only for the
   listed Studio routes and Chrome/Axe rule set. It is not a claim of full WCAG
   conformance, screen-reader interoperability, or accessibility of the absent
   administration workflow.

## Decision and safe next boundary

E-195 therefore does not connect `apps/web` to `/api/v1/admin/*`. The next
implementation boundary must first define a browser-specific authentication
and privileged-assurance contract with explicit token handling, same-origin
deployment assumptions, CSRF policy for mutations, logout/revocation behavior,
and failure UI. Only after that contract passes hostile browser tests may
authorized administration views reuse the existing redacted API responses.

No secrets, customer data, external service, publication, commit, push, pull
request, tag, or release was used by this audit.
