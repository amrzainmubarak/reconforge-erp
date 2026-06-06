# DB Import/Export Bridge

ReconForge includes a local migration bridge between legacy JSON/file workflow state and the SQLite DB foundation. The bridge is for local migration, review, backup, and restore preparation only. Legacy JSON workflows remain supported and are not deleted or rewritten by these commands.

## Commands

```bash
reconforge db export --db output/reconforge.db --output output/db_export
reconforge db import-review-state --db output/reconforge.db --input output/review_state.json
reconforge db import-close --db output/reconforge.db --input output/close
reconforge db import-accounts --db output/reconforge.db --input output/accounts
reconforge db import-control-tests --db output/reconforge.db --input output/control_testing
reconforge db backup --db output/reconforge.db --output output/backups
reconforge db restore --db output/reconforge.db --input output/backups/backup.json --force
```

Run `reconforge db init` or `reconforge db migrate` first so the local schema is current.

## Export

`reconforge db export` writes deterministic local JSON files for DB review:

- `metadata.json`
- `domain.json`
- `identity.json`
- `workflow.json`
- `audit_events.json`
- `evidence.json`
- `legacy_imports.json`

The export includes schema version, domain references, users without credential material, roles, permissions, workflow objects, workflow transition history, audit events, evidence references, and imported legacy object summaries where present. It intentionally excludes password hashes, salts, API/session token hashes, raw session tokens, environment variables, and secrets.

## Legacy Imports

The import commands read local JSON files and create DB bridge references where safe:

- `review_state.json`
- `close_checklist.json`
- `account_reconciliations.json`
- `control_tests.json`

Imports create or update workflow reference rows plus sanitized `legacy_import_records` summaries. Re-running an import updates the same deterministic bridge records instead of creating uncontrolled duplicates. The original JSON files remain the source workflow files and are not deleted.

This bridge does not implement the full DB-backed account reconciliation lifecycle, close engine, control testing workflow, approvals, or evidence vault. It only records migration references and audit events.

## Backup And Restore

`reconforge db backup` writes:

- `backup.json`
- `manifest.json`

The manifest records the backup checksum, created timestamp, schema version, and privacy warning. `reconforge db restore` validates the checksum before restoring, rejects unsupported schema versions, and refuses to overwrite an existing DB unless `--force` is provided.

Backups may contain sensitive local business data and local password hashes needed for restore. Protect backup folders like finance control evidence. Backups never include raw session tokens or the `api_sessions` table.

## Security Boundary

The bridge is local-first:

- No cloud backup.
- No SaaS storage.
- No telemetry.
- No direct ERP connector.
- No enterprise backup or disaster-recovery guarantee.
- No digital signature, legal assurance, audit opinion, or compliance certification.

Review exported and backed-up files before sharing them. Use anonymized or synthetic examples for public issues, demos, and support requests.
