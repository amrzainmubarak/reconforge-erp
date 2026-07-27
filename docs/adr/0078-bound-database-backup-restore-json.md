# ADR 0078: Bound database backup and restore JSON

Status: Accepted

Date: 2026-07-26

## Context

FI-009 restore accepted a local directory or `backup.json` beside
`manifest.json`, but both files were loaded with unbounded `read_text` and
standard `json.loads`. Duplicate keys used last-key-wins semantics, non-finite
numbers were accepted by the standard decoder, nested symlinks could be
followed, and structural validation occurred after the entire object graph had
been allocated. The manifest byte count was written but not enforced.

The current product does not accept a backup archive. Introducing ZIP/TAR in a
hardening slice would expand the attack surface and create a new compatibility
contract without a use case. This decision therefore protects the real two-file
JSON format and explicitly leaves archive support absent.

## Decision

1. Route both restore files through the shared duplicate-safe structured JSON
   engine with the named `database-backup-json-ingress-v1` profile: 64 MiB per
   file, 1,000,000 graph nodes, depth 64, 250,000 items in one collection, and
   8 MiB in one scalar. These are safety ceilings, not scale claims.
2. Before and after parsing, hash each regular non-reparse file in bounded
   1 MiB chunks while checking lstat/open/final sizes. Reject a changed file,
   oversized file, symlink/reparse point, invalid UTF-8, duplicate key,
   non-finite number, excessive graph, or unsupported JSON value with a generic
   backup error and a stable structured cause where applicable.
3. Validate a closed manifest-v1 shape, exact `backup.json` artifact identity,
   lowercase SHA-256, non-boolean byte count, supported schema version, and
   actual checksum/byte equality. Require manifest schema/time/privacy fields
   to match the backup document.
4. Validate a closed backup-v1 top-level shape, strict integer versions,
   non-empty metadata, the exact excluded session table, supported schema
   range, lists of object rows, string row keys, and only registered backup
   table names before creating a restore temporary database. Continue allowing
   missing registered tables so historical additive schema-v1 backups retain
   their existing empty-table/default migration behavior.
5. Publish JSON Schemas for current writer output and test them against a real
   generated backup. Runtime validation remains authoritative and is stricter
   about the registered table allowlist.
6. Preserve the existing safe CLI parse/checksum messages and target behavior.
   Invalid input—including `--force`—must fail before temporary restore-file
   creation or target mutation. Update manually rewritten compatibility fixtures
   to keep both manifest checksum and byte count truthful.
7. Keep FI-009 partial because `reconforge/db/importers.py::_read_json` remains
   outside this profile. Do not claim encryption, authentication, authorization,
   malware absence, real host-loss recovery, DR readiness, or archive safety.

## Consequences

Predictable resource and ambiguity attacks at the local backup restore boundary
are rejected before database allocation. Current and version-six additive
restore behavior remains covered. A previously hand-edited manifest with a
correct checksum but stale byte count now fails, as intended by the existing
manifest field.

The implementation still materializes accepted JSON within the declared
limits, so deployment memory limits remain necessary. Unkeyed manifest hashes
can be recomputed by an attacker with write access and do not prove authorship.
The local operator remains responsible for access control, encryption, secure
retention, restore authorization, and recovery exercises.

## Rollback

Revert the bounded reader/profile, runtime validators, schemas, registry links,
fixture correction, and E-063 tests together. Do not restore unbounded parsing
or last-key-wins behavior silently; any higher limits or broader format requires
a versioned reviewed policy and compatibility evidence.
