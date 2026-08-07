# ADR 0432: Add a governed ERPNext GL Entry read-only connector

- **Date:** 2026-08-07
- **Status:** accepted

## Context

The connector SDK had a provider-neutral ERP ledger example but no concrete
open-source ERP contract. ERPNext exposes a documented REST `GL Entry` resource
and uses `token` authorization plus offset pagination. Treating it as a normal
Bearer endpoint would either fail interoperability or encourage connector code
to bypass the governed HTTPS executor.

## Decision

Add `erpnext-gl-entry-readonly` as a data-only provider-specific connector.
Extend the v1 network registration with backward-compatible defaults for a
credential header scheme (`bearer` or `token`) and an optional fixed cursor
query parameter. Existing bearer/header-cursor registrations retain their
digests. The ERPNext adapter accepts only HTTPS endpoints with the exact
`/api/resource/GL%20Entry` path, binds the endpoint into the manifest, uses
`token` authorization, sends the bounded cursor as `limit_start`, validates a
closed GL Entry response, and requires one company per page.

## Verification and boundary

Focused synthetic transport tests prove token-header formatting, cursor query
construction, exact Decimal debit/credit validation, company isolation,
invalid-cursor refusal, endpoint hardening, and secret non-disclosure. The
adapter remains read-only and does not claim a live ERPNext tenant, posting,
write-back, provider-version certification, or production readiness.

## Rollback

Remove the adapter, SDK optional fields, focused tests, docs, manifest entries,
and this ADR. Existing network registrations remain compatible because the new
fields default to the original bearer/header-cursor behavior.
