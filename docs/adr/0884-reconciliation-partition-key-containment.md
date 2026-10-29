# ADR 0884: Contain unversioned reconciliation partition keys

Status: proposed. Date: 2026-10-29.

## Context

The PostgreSQL input cursor forms partition values from source columns and
JSONB text, whereas the local deterministic adapter hashes values from its
in-memory canonical record. Unversioned numeric text such as `1` and `1.00`,
currency aliases present on only one row, whitespace, and non-string JSON
values can split equivalent business records or produce different SQL and
in-memory keys. A historical checkpoint does not bind this interpretation to
an input digest and a versioned partition policy. A new normalization rule
would therefore risk silently reinterpreting historical output.

## Decision

For the local deterministic PostgreSQL worker adapter, fail closed before
matching a not-yet-completed partition when a financial amount or the selected
amount field is a partition field. Do not choose an implicit rounding or text
normalization policy. A `currency` or `ccy` partition alias must be present
as source-consistent text on every input. Source identity, currency and date
partition values must be present; generic values may be text or null, but
non-text JSON values are rejected. Reject leading/trailing whitespace,
newlines and strings beyond the matching-key limit rather than normalizing
them. Database date values are represented as ISO text for comparison with
PostgreSQL `DATE::text`.

For every streamed, not-yet-completed partition, compare the hash of each
validated input's partition values with the key supplied by the PostgreSQL
cursor before invoking the matcher or yielding the partition. A mismatch is an
execution error. In-memory fallback applies the same field and type guards;
this is not proof of cross-backend equivalence for all datasets or policies.
The ordinary unpartitioned matcher is unaffected by the partition restriction.

This deliberately rejects some previously accepted partition rules and data;
operators must review the rule and its data rather than silently retry them
under new key semantics. Generic null partition values remain allowed; their
business meaning is not certified here. A previously emitted partition may
already be committed when a later partition is rejected. Completed historical
checkpoints are skipped before the new per-record verification; they are not
validated, altered, or automatically made safe by this decision. Replaying
historical work under a changed rule needs a separately authorized procedure.

A future policy may permit financial partitioning only with an explicit
versioned canonical representation, a currency/precision/rounding contract,
record and rule fingerprints, compatible checkpoints, migration guidance,
and tested backend parity. No such policy is implemented by this containment.

## Evidence and rollback

See [canonical-source evidence](../execution/RECONCILIATION_CANONICAL_SOURCE_GUARD_2026-10-28.md)
for red/green tests, runtime scope, version limitations and retained failures.
PostgreSQL restricted-role and hosted CI checks are separate gates. Reverting
the containment restores the previously observed key ambiguity and must not
be treated as safe recovery; preserve the inputs, checkpoints and evidence.
