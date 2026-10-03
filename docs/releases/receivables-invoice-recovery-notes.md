# AR invoice acknowledgement recovery compatibility notes

This pending development change verifies invoice creation retries on SQLite and
PostgreSQL without changing the public invoice request or response shape. New
successful command receipts retain a versioned request digest and the original
creation acknowledgement in the existing internal response column. No database
schema migration is required.

Retrying the same key with a different normalized request now fails instead of
returning an unrelated historical invoice. Recovery verifies the independently
resolved invoice, ordered lines, original attribution and retained currency
policy. Successful retry continues to return the original Draft/version1 response;
authorized GET returns the current lifecycle and balance. Receipt/allocation
protocols are unchanged.

There is one explicit restriction for older raw receipts: a retry with an omitted
due date cannot prove whether the date was originally supplied or derived from
then-current terms. That retry fails closed and requires authorized GET of the
known invoice. Explicit matching dates remain eligible only when complete backing
identity can be verified. Older receipts are not rewritten, and no digest or
historical payment term is invented. Do not bypass this refusal using a new key.

Use backups that retain AR records and command history. Verified SQLite backup and
native PostgreSQL restore tests cover historical acknowledgement recovery after
payment; the public DB export contract excludes AR history. Preserve committed
receipts when rolling back. An incompatible old reader must refuse recovery and
use authorized GET rather than create a duplicate. See the
[operator runbook](../runbooks/receivables-invoice-recovery.md) and ADR0823.

This is bounded AR recovery work. It does not complete a sales/inventory/cash/GL
cycle or establish customer operating results or production deployment readiness.
