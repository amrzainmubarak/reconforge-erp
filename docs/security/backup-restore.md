# Backup And Restore Security

Implemented:

- `reconforge db backup` writes `backup.json` and `manifest.json`.
- `reconforge db backup-verify` validates the manifest and checksum.
- `reconforge db restore --dry-run` validates restore inputs without writing the target DB.
- Restore accepts exactly the adjacent `backup.json` and `manifest.json` files;
  it does not accept ZIP, TAR, or another archive/container format.
- Both JSON files pass through the named
  `database-backup-json-ingress-v1` profile before database preparation. The
  profile requires a stable regular non-reparse file, strict UTF-8 JSON,
  duplicate-key and non-finite-number rejection, and closed runtime document
  validation. It limits each file to 64 MiB, one million parsed nodes, depth
  64, 250,000 items in one collection, and 8 MiB in one scalar.
- Restore compares bounded before/after byte counts and SHA-256 digests around
  parsing, then checks the manifest-declared `backup.json` byte count and
  digest. A changed file or structure outside the closed manifest/backup
  contract fails before target preparation.
- Restore refuses to overwrite an existing DB unless `--force` is used.
- Schema migrations are regenerated locally rather than trusted from backup rows. A supported older backup is restored against its source schema and then upgraded through the current migrations.
- Missing additive columns are omitted from parameterized inserts so SQLite applies defaults from the trusted local schema. Restore does not parse SQL defaults in Python and does not execute SQL from backup content. Missing required columns without defaults fail closed.
- Restore checks SQLite foreign-key relationships before replacing the selected target database.

Partially implemented:

- Backups include enough local DB state to restore workflows and may include credential verifier fields.
- Backups exclude raw tokens and the API sessions table.
- Manifest SHA-256 values provide unkeyed local integrity/self-consistency,
  not publisher authentication, signature assurance, encryption, or protection
  against an attacker able to replace both files.
- Schema 7 backups include organization, legal-entity, branch, currency-reference, and fiscal-period master data.
- Schema 8 backups include charts, expanded accounts, dimensions, journal definitions, balanced ledger entries, immutable lines, and dimension links. Restore rebuilds Validated/Voided statuses only after all lines are loaded and their balance triggers pass.
- Schema 9 backups include inventory units, items, warehouses, locations, lot/serial references, movements, and exact-quantity lines. Restore rebuilds Posted/Voided states only after Draft headers and lines are loaded so status triggers recheck movement direction and review metadata.
- Schema 10 backups include count sessions/lines and reorder rules. Restore loads counts as Draft, restores immutable snapshot/result lines, then replays valid lifecycle transitions so count-integrity triggers remain active.
- Schema 11 backups include FIFO policies, valuation documents, input costs, valuation lines, cost layers, and layer consumptions. Restore loads valuation evidence without trusting final status/total/link fields, rebuilds movement and Finance Core lifecycle state, replays valuations chronologically, and verifies global layer balances before replacing the target database.
- Schema 12 backups include valuation-reversal headers and immutable layer effects. Restore loads reversal headers as Draft, defers protected mirror Finance statuses, restores effects, replays reversal lifecycle after original valuations, and verifies each layer against both consumptions and `Restore`/`Remove` effects before replacing the target database.

Roadmap:

- More formal schema compatibility reporting.
- More operator runbooks for rollback and upgrade windows.
- Preserve the bounded legacy DB importer profile and design centralized
  import/restore authorization, encryption/key management, malware hooks, and
  real recovery exercises.

PostgreSQL native-adapter rehearsal is opt-in and must use disposable service
definitions. Set `RECONFORGE_TEST_POSTGRES_SOURCE_SERVICE` to the source service
and `RECONFORGE_TEST_POSTGRES_MAINTENANCE_SERVICE` to a maintenance service that
may create and drop only isolated drill databases. Put `pg_dump`, `pg_restore`,
`createdb`, `dropdb`, and `psql` on `PATH`. The test creates a random
`reconforge_restore_*` database, verifies the encrypted round-trip through the
Application boundary, and drops that exact database. Never point this rehearsal
at a production maintenance role.

Not supported:

- Cloud backup.
- Enterprise disaster recovery guarantee.
- Compliance certification or audit assurance.

Protect backup files like sensitive finance and local identity data.

Exact fractional defaults must be declared as quoted canonical text or integer
minor units. An unquoted SQLite fractional numeric default can have REAL
semantics and is not an exact-decimal guarantee.
