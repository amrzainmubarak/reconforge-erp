# PostgreSQL audit administration

## Purpose and boundary

`GET /api/v1/admin/audit/events` is the redacted PostgreSQL administration
surface for the current two audit sources. It is not a global audit ledger, a
compliance conclusion, or a replacement for evidence export.

The route needs a human principal with `audit.read`, recent privileged
assurance, and an operator-owned cursor signing key. It returns at most 200
events per request in ascending UTC timestamp/source/event order. Save and
reuse only the opaque `next_cursor` returned for the same tenant and route;
altered or cross-tenant cursors are rejected.

The response deliberately excludes raw actor IDs and labels, object IDs,
request IDs, reasons, and metadata. `actor_digest`, `object_digest`, and
`metadata_digest` are SHA-256 values for correlation inside an authorized
review process, not reversible values.

`GET /api/v1/admin/audit/verify` needs `audit.verify` and the same human
assurance. It verifies `domain` and `ledger_control` separately. An overall
`ok` is true only when both source chains verify. The display order is not a
cross-source cryptographic chain; compare each source's sequence and head hash
only with the corresponding source result.

## Operator steps

1. Configure a cursor signing key of at least 32 bytes in the server process.
2. Grant `audit.read` or `audit.verify` only to an approved human role.
3. Complete the configured recent step-up (and user-verified WebAuthn when
   enabled), then page the browse endpoint or call verify.
4. If verification is not `ok`, retain the returned source/issue codes and
   head hashes, stop relying on that chain for the affected review, preserve
   the database and logs, and follow the incident process before repair.
5. Review historic `audit.read`/`audit.verify` service-account grants after
   applying migration 0053. They are denied at runtime but remain recorded so
   the migration does not delete access state silently.

## Limits

The view has no global audit sequence, does not redact the historical local
SQLite audit API, does not prove object-store immutability or legal retention,
and has no hosted deployment or independent assurance evidence.
