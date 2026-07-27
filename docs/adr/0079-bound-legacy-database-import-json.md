# ADR 0079: Bound legacy database import JSON

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Platform Security, Domain Integrity
- Related: ADR 0071, ADR 0078, FI-009, R-018, P0-SEC-009

## Context

The local database bridge imports account_reconciliations.json and
control_tests.json through reconforge/db/importers.py::_read_json. The reader
previously used an unrestricted Path.read_text plus json.loads. Duplicate keys,
non-finite constants, deep/wide documents, very large scalars, Windows reparse
points, and changes around parsing had no shared bounded preflight. A top-level
object with no recognized collection and at least one non-object value silently
became an empty import, while documents containing multiple recognized aliases
selected the first alias by code order.

The bridge is a compatibility reader, not a full account-reconciliation or
control-testing domain importer. Existing direct-list, single named-envelope,
and identifier-keyed object-map inputs must remain readable.

## Decision

1. Route both import files through the shared duplicate-safe JSON engine under
   the named database-legacy-import-json-ingress-v1 profile.
2. Limit each file to 16 MiB, 500,000 nodes, depth 32, 50,000 items in one
   collection, and 1 MiB in one scalar.
3. Require a stable regular non-reparse path. Compare bounded raw-byte size and
   SHA-256 before and after parsing; reject instability with the existing
   path/value-free public parse error.
4. Accept direct record lists, exactly one recognized list envelope, an empty
   object, or an identifier-keyed object map. Reject multiple recognized
   aliases, arbitrary non-record objects, non-list envelope values, and
   non-object records before database inspection or mutation.
5. Pass the digest and byte count of the parsed bytes into import records,
   audit metadata, and outbox metadata with the named ingress profile. Do not
   recalculate provenance from a later mutable file state.
6. Publish separate current compatibility schemas for account-reconciliation
   and control-test imports. The schemas deliberately leave individual legacy
   record fields open; domain-semantic expansion requires a separate versioned
   contract.

## Compatibility and consequences

- Existing direct lists, the four source-specific aliases, identifier-keyed
  maps, empty objects, idempotent upserts, safe summaries, audit events, and
  outbox effects remain supported.
- Previously ambiguous alias documents and arbitrary objects that silently
  imported zero records now fail visibly. This is a data-quality and integrity
  correction, not a silent migration.
- The SHA-256 value is unkeyed local consistency metadata, not authentication,
  authorization, a signature, or non-repudiation.
- The current DB bridge accepts JSON files only. No archive/decompression
  format is introduced or implied.
- FI-009 parser coverage becomes bounded, but encryption, centralized
  import/restore authorization, malware scanning, full record semantics,
  cross-edition recovery, and real host/filesystem DR exercises remain open.

## Rollback

Revert the reader/profile/provenance changes and remove the two schemas and
their dedicated test. Existing databases require no migration: the new fields
are stored only inside existing JSON summary/audit/outbox metadata. Rollback
would re-open duplicate/resource/ambiguity and silently-empty input risks, so it
must be recorded against R-018 rather than described as equivalent safety.
