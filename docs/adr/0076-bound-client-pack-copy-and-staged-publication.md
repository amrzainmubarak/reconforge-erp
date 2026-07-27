# ADR 0076: Bound client-pack copying and stage complete publication

Status: Accepted

Date: 2026-07-26

## Context

FI-012 had bounded JSON and CSV redaction, but other text was loaded with an
unbounded replacement-decoding `read_text`, non-redacted artifacts used
unbounded `copy2`, evidence traversal had no entry/file/aggregate ceiling, and
the destination directory was cleared before the complete pack existed. A
failure in a later copy, source recheck, summary, or manifest could therefore
destroy the previous pack and leave a partial replacement.

## Decision

1. Treat the selected client-pack file set as one immutable generation
   snapshot. Bound evidence enumeration to 20,000 entries and the selected set
   to 10,000 regular non-symlink files, 64 MiB per file, and 512 MiB aggregate.
   Files appearing after selection are neither copied nor manifested.
2. Decode redacted text as strict UTF-8 and process at most one 1 MiB line at a
   time. Reject invalid encoding or overlong lines with a stable code-only
   cause; do not use replacement decoding or whole-file text reads.
3. Copy non-redacted bytes in 1 MiB chunks with open-file size checks, a 64 MiB
   ceiling, a same-directory temporary target, and change detection before
   replacement. Do not preserve source filesystem metadata in redistributed
   packs.
4. Preflight the complete selected set and record its fingerprints before
   creating a staging directory. Build summaries, copied/redacted artifacts,
   final source recheck, and manifest entirely in a uniquely named sibling
   staging directory.
5. Publish a fresh destination with one same-filesystem directory rename. For
   an existing destination, rename it to a unique rollback sibling, rename the
   completed staging directory into place, restore the rollback directory on a
   handled publication failure, and delete the old directory only after the
   new name is active.
6. Reject output paths equal to or containing the source tree, any output below
   the inventoried `evidence/` subtree, and symlink/non-directory output
   targets. Preserve the historical demo-compatible `source/client_pack`
   location because top-level non-evidence subdirectories are not candidates;
   its sibling staging name is hidden and the selected set is already frozen.
   Returned artifact paths are rebased after rename.
7. Keep FI-012 and R-018 partial/High. On Windows, replacement of an existing
   non-empty directory requires two renames and is not an observer-atomic or
   crash-atomic transaction. A process/host crash between those renames can
   leave a rollback sibling requiring an explicit recovery procedure. Malware
   scanning, authenticated provenance, disclosure authorization, redaction
   completeness, and remaining parser surfaces are separate controls.

## Consequences

Predictable oversized, excessive, symlinked, malformed-text, late-created, or
concurrently changed sources fail without altering the existing destination.
Handled generation and publication failures remove staging content and restore
the old pack. Successful replacement intentionally removes stale hidden files
instead of retaining undisclosed content from an older generation.

The policy is deliberately conservative: previously accepted invalid UTF-8,
very long single-line generated text, files over 64 MiB, aggregate packs over
512 MiB, source-containing or evidence-nested output paths, and symlinked inputs now fail closed. This
is a security/resource boundary, not evidence that accepted content is safe to
share.

## Rollback

Revert this ADR, the bounded copy/text/staging helpers, registry and manifest
links, and the dedicated E-061 tests together. Do not silently restore
destructive pre-generation destination clearing or unbounded reads/copies;
restoring those compatibility behaviors requires a new reviewed risk decision.
