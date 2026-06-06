# Backup And Restore Security

Implemented:

- `reconforge db backup` writes `backup.json` and `manifest.json`.
- `reconforge db backup-verify` validates the manifest and checksum.
- `reconforge db restore --dry-run` validates restore inputs without writing the target DB.
- Restore refuses to overwrite an existing DB unless `--force` is used.

Partially implemented:

- Backups include enough local DB state to restore workflows and may include credential verifier fields.
- Backups exclude raw tokens and the API sessions table.

Roadmap:

- More formal schema compatibility reporting.
- More operator runbooks for rollback and upgrade windows.

Not supported:

- Cloud backup.
- Enterprise disaster recovery guarantee.
- Compliance certification or audit assurance.

Protect backup files like sensitive finance and local identity data.
