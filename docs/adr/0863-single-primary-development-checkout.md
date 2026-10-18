# ADR0863: Keep development in the primary checkout

- Status: Accepted by explicit user instruction
- Date: 2026-10-18

## Context

The user requested consolidation into the primary repository directory and
removal of secondary worktrees, with no further worktrees. The former primary
checkout lagged the latest integrated source by 750 commits and retained two
local changes to static SQL assembly. Four secondary worktrees existed, with
46 additional stale Git registrations.

## Decision

Use `F:\reconforge-erp` for all ongoing work. Use branches in that directory
when needed, without creating worktrees. The repository's `AGENTS.md` carries
this directive above the older execution instructions.

Consolidate from `bfc138a13c05513dc5c6e7bf23c81f013a0df123`: every distinct leaf
patch is already represented there. Preserve all previous registered heads in
archive refs and a verified Git bundle, keep the original primary edits in a
stash/patch/file copies, and archive ignored artifacts other than regenerable
dependency and interpreter caches. Verify hashes before deleting checkouts.

## Consequences and rollback

Only the primary directory remains. Existing business capability and release
acceptance status is unchanged. Historical path strings remain evidence of
their original runs. Recovery uses the bundle, stash and artifact ZIPs indexed
in `docs/execution/WORKSPACE_CONSOLIDATION_2026-10-18.md`; it does not require a
new Git worktree. The old SQL patch must be recovered against its recorded old
base, rather than blindly applied over newer financial migrations.
