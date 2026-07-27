# ADR 0077: Integrity-checked client-pack publication recovery

Status: Accepted

Date: 2026-07-26

## Context

ADR 0076 stages a complete client pack and restores the previous directory on
handled errors. Replacing an existing non-empty directory still requires an
old-to-rollback rename followed by a staging-to-output rename on Windows. An
abrupt process, host, or storage interruption may bypass exception cleanup and
leave one of several filesystem states. Guessing from similarly named siblings
could delete or publish unrelated bytes.

An unkeyed SHA-256 digest cannot authenticate a marker or protect against an
actor who can rewrite both the marker and directories. Calling such a marker
authenticated would overstate the control and conflict with the requirement to
avoid custom cryptography.

## Decision

1. Before the first destructive rename, write a schema-v1 JSON transaction
   marker beside the output through a temporary file, flush and `fsync` its
   bytes, then replace the marker name. It contains only a random 128-bit
   transaction identifier, exact sibling basenames, phase, bounded previous and
   staged tree SHA-256 digests, schema/artifact identifiers, an integrity
   boundary, and a canonical marker digest. It contains no absolute source or
   output path and no financial row.
2. Update the marker after the previous directory moves and after the staged
   directory publishes. Keep handled-error rollback. Allow an unhandled
   `BaseException` to model real abrupt loss in tests rather than misclassifying
   normal exception cleanup as crash recovery.
3. Add only the explicit
   `reconforge report client-pack-recover --output <directory>` operation. Do
   not auto-recover during generation. Require exactly one valid marker, exact
   bound sibling names, no additional matching sibling, regular directories,
   no symlink/reparse point, unchanged bounded tree digests, and one of four
   closed states:

   | Output | Staging | Rollback | Accepted phase | Action |
   | --- | --- | --- | --- | --- |
   | present previous | present staged | absent | `prepared` | discard verified staging and preserve previous |
   | absent | present staged | present previous | `prepared` or `previous-moved` | restore previous and discard verified staging |
   | present staged | absent | present previous | `previous-moved` or `published` | keep verified staged output and discard verified previous |
   | present staged | absent | absent | `published` | confirm verified output and remove the marker |

4. Refuse every other state and perform no mutation when a marker or tree
   digest is invalid, multiple/temporary markers exist, a sibling is unknown,
   a path is a reparse point, or the state is ambiguous. Bound recovery hashing
   with the same client-pack per-file, count, entry, and aggregate family,
   including hidden content.
5. Describe this as local integrity/self-consistency and explicit recovery, not
   authentication, a signature, provenance, actor authorization, crash-atomic
   publication, or guaranteed host-loss durability. File `fsync` does not prove
   parent-directory durability on every operating system, filesystem, storage
   stack, or power-loss mode.

## Consequences

The known two-rename states can be resolved deterministically without scanning
for a plausible directory or silently choosing new versus old content. The
default recovery direction is conservative before publication and preserves a
fully published new pack after verifying its staged digest.

Existing-output replacement remains temporarily invisible between renames and
is neither observer-atomic nor crash-atomic. A local attacker with write access
to all transaction artifacts can forge unkeyed digests. Real process kill,
power loss, remote filesystem, journal replay, and directory-entry durability
tests remain necessary before making a stronger recovery claim.

## Rollback

Revert the marker/recovery code, CLI command, runbook, registry links, and
dedicated E-062 tests together. Keep ADR 0076 handled-error rollback. Never add
automatic recovery or delete unknown siblings to emulate the removed command;
any replacement protocol requires a new reviewed state table and migration.
