# Backup And Restore Security

Implemented:

- `reconforge db backup` writes `backup.json` and `manifest.json`.
- `reconforge db backup-verify` validates the manifest and checksum.
- `reconforge db restore --dry-run` validates restore inputs without writing the target DB.
- Restore refuses to overwrite an existing DB unless `--force` is used.
- Schema migrations are regenerated locally rather than trusted from backup rows. A supported older backup is restored against its source schema and then upgraded through the current migrations.
- Restore checks SQLite foreign-key relationships before replacing the selected target database.

Partially implemented:

- Backups include enough local DB state to restore workflows and may include credential verifier fields.
- Backups exclude raw tokens and the API sessions table.
- Schema 7 backups include organization, legal-entity, branch, currency-reference, and fiscal-period master data.
- Schema 8 backups include charts, expanded accounts, dimensions, journal definitions, balanced ledger entries, immutable lines, and dimension links. Restore rebuilds Validated/Voided statuses only after all lines are loaded and their balance triggers pass.
- Schema 9 backups include inventory units, items, warehouses, locations, lot/serial references, movements, and exact-quantity lines. Restore rebuilds Posted/Voided states only after Draft headers and lines are loaded so status triggers recheck movement direction and review metadata.
- Schema 10 backups include count sessions/lines and reorder rules. Restore loads counts as Draft, restores immutable snapshot/result lines, then replays valid lifecycle transitions so count-integrity triggers remain active.
- Schema 11 backups include FIFO policies, valuation documents, input costs, valuation lines, cost layers, and layer consumptions. Restore loads valuation evidence without trusting final status/total/link fields, rebuilds movement and Finance Core lifecycle state, replays valuations chronologically, and verifies global layer balances before replacing the target database.
- Schema 12 backups include valuation-reversal headers and immutable layer effects. Restore loads reversal headers as Draft, defers protected mirror Finance statuses, restores effects, replays reversal lifecycle after original valuations, and verifies each layer against both consumptions and `Restore`/`Remove` effects before replacing the target database.

Roadmap:

- More formal schema compatibility reporting.
- More operator runbooks for rollback and upgrade windows.

Not supported:

- Cloud backup.
- Enterprise disaster recovery guarantee.
- Compliance certification or audit assurance.

Protect backup files like sensitive finance and local identity data.
