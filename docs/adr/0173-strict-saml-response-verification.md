# ADR 0173: Strict SAML Response verification

## Status

Accepted — 2026-07-28

## Context

SAML requires XML Signature, canonicalization, wrapping defenses, conditions,
audience, destination, recipient and request-correlation checks. Implementing
those primitives locally is prohibited. Provider metadata and certificate
rotation also need an explicit trust boundary.

## Decision

Use locked python3-saml 1.16.0 with xmlsec 1.3.17 and lxml 6.1.1. Configure one
fixed IdP certificate and credential-free HTTPS endpoints per provider. Strictly
require a signed Response, one Assertion, expected destination, recipient,
InResponseTo, issuer, audience and NameID. Independently allowlist the validated
SignatureMethod and DigestMethod. Normalize only bounded configured attributes
after successful validation; expose no raw XML or library error.

## Consequences

Real RSA-SHA256 SAML verification is executable without home-grown XML Signature.
Certificate rotation is explicit. The current library emits a Python 3.14
`utcnow()` deprecation warning and requires upgrade monitoring. Durable replay,
identity links, sessions, logout and API integration still block P3-ENT-001.
