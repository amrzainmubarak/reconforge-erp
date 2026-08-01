# ADR 0200: Studio and API Share One Host-Bounded HTTPS Origin

- Status: accepted
- Date: 2026-07-30

## Context

The administration browser session uses a host-only Secure cookie and a
session-bound CSRF proof. A development proxy demonstrated the contract but did
not provide a deployable origin, TLS termination, host validation, HSTS, or a
Content Security Policy for the built Studio.

## Decision

`reconforge api serve` may optionally serve a pre-built Studio directory after
all API routes. This produces one origin for HTML, immutable assets, and
`/api/v1/*`. Enabling a web root requires at least one exact allowed host.
Direct TLS requires a certificate and key together; reviewed upstream TLS
termination must be declared explicitly. HSTS is emitted only in either secure
transport mode.

The response policy denies framing, objects, foreign scripts, foreign network
connections, foreign forms, and base-URI rewriting. Vite's external scripts
and styles are allowed from the same origin. Dynamic React style attributes are
the only inline-style allowance; inline scripts and inline style elements
remain denied. Missing asset-like paths remain 404, while extensionless GET/HEAD
routes fall back to `index.html` for client routing.

Forwarded-host or forwarded-protocol headers are not trusted by this boundary.
An upstream proxy must rewrite a validated Host value and must not expose the
backend directly. This ADR does not select a certificate authority, cipher
policy, load balancer, WAF, public DNS, or production topology.

## Consequences

- The Secure administration cookie is no longer dependent on a development
  proxy in the supported direct-TLS path.
- Host-header attacks and accidental alternate origins fail before routing.
- Community/API-only execution is unchanged unless the new options are used.
- This is bounded localhost deployment evidence, not internet-facing or
  Enterprise-readiness assurance.

## Rollback

Stop passing `--web-root`, `--allowed-host`, and TLS/secure-transport options.
The API-only behavior and schemas remain unchanged; no data migration is
required.
