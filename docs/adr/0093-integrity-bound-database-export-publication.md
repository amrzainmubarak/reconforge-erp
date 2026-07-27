# ADR 0093: Stage and integrity-bind public database export publication

- Status: Accepted
- Date: 2026-07-27
- Decision owners: Platform Architecture, Data Engineering, Security, Financial Controls
- Scope: FI-013 SQLite public database export filesystem publication

## Context

Format-v1 database exports wrote their nine JSON documents directly into the
destination. A handled filesystem failure could expose a partial mix of old and
new files, and a successful rerun retained stale files. There was no closed
artifact inventory or integrity value for verifying an interrupted replacement.

## Decision

- Build and validate all payloads before filesystem mutation, then write every
  artifact into a same-parent private staging directory.
- Add `export_manifest.json` as an additive manifest. It records the exact nine
  format-v1 artifact basenames, byte lengths, SHA-256 digests, and schema versions.
- Publish a fresh export with one same-filesystem directory rename. Replace an
  existing export through an integrity-bound marker and sibling rollback directory.
  Handled failures restore the prior directory.
- Provide `reconforge db export-recover --output ...` for exactly one unambiguous
  interrupted transaction. Recovery verifies marker integrity, sibling names,
  and both tree digests before restoring or finalizing.
- Reject reparse points, unsupported prior-tree entries, unexpected siblings,
  changed artifacts, malformed markers, more than 32 prior files, or more than
  1 GiB of prior files.
- Append `db_exported` only after filesystem publication succeeds. Filesystem
  publication and the SQLite audit commit are not one atomic transaction.

## Compatibility and limitations

The existing nine filenames, format-v1 payload shapes, CLI options, and encodings
are unchanged. The manifest is an additive tenth file; exact-set consumers must
allow it before upgrading. A pre-manifest export remains replaceable/recoverable
because its bounded prior tree is independently digested.

Directory rename is atomic only under local-filesystem guarantees. Existing-tree
replacement has an observer interval between renames. Sudden loss before a marker
is durable can leave an unbound staging sibling requiring manual inspection;
ambiguous states fail closed. SHA-256 detects change but does not authenticate a
source. This does not prove authorization, semantic correctness, malware safety,
remote-filesystem behavior, durability, or production scale.

## Rollback

Revert publication, recovery, manifest schema, tests, and governance together.
Existing payloads remain readable after removing the additive manifest. First
recover or inspect every transaction sibling; never delete ambiguous rollback data.
