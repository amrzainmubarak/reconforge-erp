# Retain AR currency policy before financial interpretation

Status: accepted for backend persistence; API and React exposure remain a separate gate.
Date: 2026-10-03
Scope: PROD033, SQLite 49 and PostgreSQL 0099_pg_receivables_policy.

New customer, invoice and receipt records capture precision, rounding, registry
version and digest. Reads verify the record against its retained snapshot. New
financial effects require full policy affinity with their authoritative parents
and the selected write policy. A current registry cannot reinterpret history.
The closed public policy contains eleven interpretation/provenance fields.

Historical all-NULL policy remains explicitly unverified and readable as raw
minor units. Financial mutation of that unresolved history is refused. This
migration neither assigns a historical scale nor repairs old data automatically.
Partial or forged captured tuples fail verification. PostgreSQL composite foreign
keys preserve parent policy even when a child is hidden by RLS; parent changes
and child creation serialize at the database boundary. No SECURITY DEFINER or
tenant-context reset is introduced.

SQLite standalone AR may capture the bundled policy when a currency master is
absent. This is an explicit opt-in; existing Finance policy callers retain their
strict master prerequisite. Present master precision must be an exact integer.
Cached retries verify their monetary interpretation against the scoped retained
source while preserving the original cached lifecycle projection. Backup and
restore verify snapshots and parent/allocation affinity before publication.

Acceptance: one final selection passes 216 tests without skips in 285.514s;
provisioning/migration/cleanup takes 301.017s. Nine runtime/schema and nine test
hashes stay unchanged. Actual PostgreSQL 16.14 dump/restore retains eleven table
digests and rejects fifteen legacy financial mutations plus three forged tuples
through a nonowner connection. JPY 0 and KWD 3, registry rebinding, hidden-child
policy affinity, concurrency, cache tampering, malformed master and corrupt
backup publication are independently covered. Original failed and superseded
runs remain separate in RECEIVABLES_POLICY_2026-10-03.json.

Compatibility: old public request/response contracts remain unchanged at this
checkpoint. Receipt retry after disabling its customer still has an existing
active-customer prerequisite; authoritative GET remains readable. That recovery
limitation, exact browser amounts, historical policy repair, generated GL and
complete trade cycles are separate work.

Rollback: preserve a verified backup before upgrade. PostgreSQL downgrade is
allowed only when all retained AR policy rows are empty or legacy all-NULL;
captured/partial rows refuse downgrade. Redeploy a compatible reader without
rescaling or deleting captured evidence. No production rollback has been run.
