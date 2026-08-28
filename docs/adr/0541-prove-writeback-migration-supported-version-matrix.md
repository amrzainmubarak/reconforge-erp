# ADR 0541: Prove the write-back migration on the declared PostgreSQL version matrix

- Status: Accepted
- Date: 2026-08-22
- Scope: E-827 PostgreSQL 16.14 and 17.10 write-back identity migration evidence

## Context

E-826 proves that migration 0089 refuses drifted write-back history without
mutation and upgrades an independent pre-drift restore on PostgreSQL 17.10.
The repository also declares a digest-pinned PostgreSQL 16 service in CI. One
version cannot establish parity across these two actually declared runtime
profiles, and duplicating the drill would permit the two paths to diverge.

## Decision

Extract the existing E-826 execution into one reusable observation function
while preserving its CLI, retained report schema, default image, and output.
Run that exact function sequentially against the two closed image identities:

- PostgreSQL 16.14 through the CI image digest; and
- PostgreSQL 17.10 through the existing drill image digest.

Retain one closed matrix report that embeds both complete observations and
requires identical canonical valid and invalid history digests. Each cell must
prove dump listing, refusal without revision/history/trigger mutation,
independent restore and upgrade, enhanced INSERT refusal, and exact cleanup.
Bind the matrix to the migration commit/source, both runner sources, and the
closed supply-chain policy source.

This is an evidence matrix for two declared versions, not an open-ended support
promise. Runs are sequential single-node executions on one Docker host so they
do not establish concurrency, rolling upgrade, replication, HA, or DR parity.

## Security and financial integrity

Both cells use digest-pinned official images, generated synthetic credentials,
shell-free argument vectors, isolated databases, and the same deterministic
write-back history. A version mismatch, history divergence, false check,
additional field, ungoverned image, or incomplete cleanup fails closed.

No provider is contacted, no accounting entry is posted, and no invalid history
is altered to pass the audit.

## Compatibility

The E-826 command and report remain valid and continue to default to PostgreSQL
17.10. Product APIs, migrations, schemas, write-back behavior, and deployment
defaults do not change. The refactor affects only verification code.

## Rollback

Revert the matrix assets and restore the prior single-run implementation if the
shared observation boundary is defective. Preserve the E-826 report and never
rewrite lifecycle history as rollback. Removing a matrix cell must also remove
the corresponding support wording and retained evidence.
