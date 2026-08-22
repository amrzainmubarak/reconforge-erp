# ADR 0540: Prove write-back migration refusal and independent restore

- Status: Accepted
- Date: 2026-08-22
- Scope: E-826 PostgreSQL write-back identity migration recovery evidence

## Context

ADR 0539 requires Alembic 0089 to audit existing write-back lifecycle history
before installing the stronger INSERT/UPDATE/DELETE trigger. Static migration
tests and valid-history runtime checks did not prove the most important failure
case: a PostgreSQL database already containing proposal-identity drift must be
refused without advancing its revision, rewriting evidence, or replacing its
legacy trigger. Operators also need evidence that a valid pre-drift backup can
be restored into an independent database and upgraded successfully.

Treating a refused audit as a generic deployment error would invite unsafe
manual deletion or rewriting of append-only evidence. The recovery boundary
therefore needs an executable, digest-bound drill with explicit limitations.

## Decision

Retain a Docker-based verification runner and a closed JSON evidence artifact.
The runner uses an exact digest-pinned PostgreSQL 17.10 image, runtime-generated
synthetic credentials, two isolated databases, and native `pg_dump`/
`pg_restore` from the container.

The drill:

1. upgrades the source database to 0088 and inserts a valid proposed/approved
   history;
2. creates and lists a custom-format pre-drift backup and binds its SHA-256;
3. inserts a drifted dispatched version that the former trigger permits;
4. proves that upgrade to 0089 raises the expected audit refusal while the
   revision, history digest, and legacy trigger definition remain unchanged;
5. restores the pre-drift backup into an independent database, proves the
   restored revision and history digest, and upgrades it to 0089;
6. proves the valid history remains byte-canonically equivalent and the new
   direct-INSERT guard rejects proposal drift; and
7. verifies disposal of the exact temporary container before writing a report.

The JSON Schema fixes the image, PostgreSQL version, source/target revisions,
required checks, history cardinalities, digest formats, and limitation set. It
also binds the last commit that changed migration 0089 and canonical source
SHA-256 values for the runner and migration. The report digest covers every
field except itself using canonical sorted JSON.

## Security and financial integrity

This prevents an operator from confusing a failed audit with a partial or
successful migration. It demonstrates that invalid evidence is neither erased
nor normalized and that a known-valid backup can be upgraded separately.
Credentials and records are synthetic; subprocesses use argument vectors with
no shell expansion; the output contains no credentials or row payloads.

The drill does not authorize editing invalid history, select a business
resolution for the drift, authenticate a provider, post accounting entries, or
establish production recovery readiness.

## Compatibility

No product API, schema, migration, or runtime default changes. The runner and
artifact are verification assets. Valid databases continue to upgrade through
0089. Invalid databases continue to fail closed exactly as required by ADR
0539.

## Rollback

Removing this verification asset does not alter a deployed database, but it
would remove repeatable evidence for the failure/recovery path. Never use
deletion or mutation of append-only lifecycle rows as rollback. Preserve the
refused database and its backup, investigate the drift, and use an independently
reviewed corrective migration or a verified pre-drift restore.
