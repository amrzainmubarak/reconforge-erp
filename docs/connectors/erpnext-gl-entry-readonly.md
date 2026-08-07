# ERPNext GL Entry read-only connector

`erpnext-gl-entry-readonly` is a provider-specific, read-only integration for
ERPNext's open REST resource `GL Entry`. Frappe documents generated REST
resources, `token` authentication, and `limit_start` pagination in its
[REST API documentation](https://docs.frappe.io/framework/user/en/api/rest).
It runs through the governed HTTPS
executor and supports ERPNext's `token` authorization format, bounded
`limit_start` pagination, exact Decimal debit/credit text, company scoping,
idempotent reads, retry limits, and canonical response digests.

The operator supplies an HTTPS endpoint whose path is exactly
`/api/resource/GL%20Entry` and a secret reference. The token is resolved only
at runtime; it is never persisted, logged, or returned. The connector preserves
debit and credit source fields and exposes a derived signed amount without
posting or mutating ERPNext.

This is provider-specific contract and synthetic transport evidence. It is not
a live ERPNext tenant, credential-vault verification, accounting-posting,
write-back, provider SLA, HA/DR, or production-readiness claim.
