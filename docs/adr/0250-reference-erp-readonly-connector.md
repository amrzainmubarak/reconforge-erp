# ADR 0250: Add a provider-neutral ERP read-only reference connector

- **Status:** Accepted
- **Date:** 2026-08-03

## Decision

Ship `reference-erp-readonly` as a manifest-driven, data-only HTTPS reference
connector. Its closed page schema carries entity, account, posting date,
currency, exact Decimal amount text, and document reference. Pages are bounded,
cursor/idempotency governed, entity-scoped, and canonically digested.

## Boundary

This is synthetic SDK evidence, not a live ERP integration. No provider
credential, write capability, posting authority, or ERP interoperability claim
is introduced. A live provider requires a separately reviewed manifest,
credentials, provider-version contract, and governed write-back approval.

## Reversibility

The module is additive and can be removed with its manifest and tests without a
migration or change to existing connector behavior.
