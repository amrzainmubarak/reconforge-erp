# Upgrade and rollback operations

The normative v1 plan is `docs/schemas/upgrade_plan.schema.json`; the exact supported
transitions are `upgrade-supported-versions.v1.json`. It accepts no
commands, scripts, environment substitutions, secret values, or executable hooks.
Its operator version is distinct from the deployed source/target versions, so the
v0.7.1 operator can upgrade a v0.7.0 deployment. Its release digest must refer to a separately verified release manifest; hashing
bytes does not by itself verify a release signature or provenance.

The lifecycle is prepare, independent approval, atomic execution claim, ordered
apply/verify, and completion. All resources preflight before mutation. A failure
rolls applied resources back in reverse order. An interrupted adapter reports one
of three states: `not_applied`, a verified receipt, or unknown. Unknown state makes
the run failed and requires isolation/manual investigation; operators must not
retry or declare rollback.

The application adapter installs one exact local wheel with `--no-index --no-deps`,
rejects links/special files, smoke-imports the staged version, switches directories,
and quarantines a rolled-back target. Configuration preserves the public
`reconforge.yml` format, applies strict financial-input validation, switches a closed
digest marker, and quarantines the target on rollback. The local object adapter verifies
every immutable content/sidecar pair and changes only a deterministic catalog; object
bytes never move. SQLite uses an online copy plus isolated migration drill and removes
stale WAL/SHM before exact restore. PostgreSQL creates an encrypted native backup,
restores and migrates an isolated database, removes the drill database, upgrades the
source, and uses the supported Alembic downgrade for normal rollback; a digest-bound
encrypted backup remains for governed recovery. Signed packs reuse the existing
maker-checker `PackLifecycleStore`; no executable pack hook exists.

Keep release signature/provenance verification, PostgreSQL service credentials, the
32-byte backup key, free capacity, exclusive maintenance windows, and journal/recovery
directories under operator control. Do not retry a `failed`/unknown run: isolate the
named resources and retain journal, backup, rollback, and quarantine artifacts. These
drills do not prove zero downtime, HA, DR, air gap, compliance, certification, production
key custody, or Enterprise readiness.
