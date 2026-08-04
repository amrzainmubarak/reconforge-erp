# ADR 0331: Signed connector packages require conformance admission

## Status

Accepted — 2026-08-04

## Context

ReconForge already verifies bounded Ed25519 connector envelopes against an
operator-owned publisher registry. Signature validity alone does not establish
that the manifest is safe to admit: a package must also satisfy the connector
SDK's read-only, synthetic-sandbox, schema, threat-model, and network-egress
contract. The package format is data-only and must never become an executable
plugin loader.

## Decision

Add an explicit admission boundary after signature verification:

1. `load_verified_package_for_admission` loads and authenticates the envelope
   against exactly one trust source;
2. `admit_verified_package` runs `verify_manifest_portfolio` on the signed
   manifest and rejects non-conformant packages before returning admission;
3. the returned `VerifiedConnectorPackage` binds the manifest digest, trust
   registry version/digest, signature digest, and canonical admission digest;
4. admission exposes only data and checks; it does not import, execute, or
   install package code.

## Consequences

Signed read-only packages now have a reviewable trust-plus-conformance gate
that can be used by a future operator-controlled registry. Local and provider
runtime permissions remain separate. This does not establish a live ERP/bank
connector, provider compatibility, write-back capability, or production
package marketplace.

## Rollback

Call the existing signature-only reader for diagnostics, but do not use it as a
runtime admission path. Removing the admission helper is additive and leaves
existing envelope verification and stored evidence intact.
