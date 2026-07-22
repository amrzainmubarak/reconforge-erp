# DB-Backed Finance Workflow Foundations

ReconForge now includes local SQLite-backed foundations for finance workflow records. These workflows are local-first and self-hosted-capable: they read local exports, write to the selected local DB, and do not upload data to cloud services.

Implemented foundations:

- Account reconciliation records from local trial-balance CSV/JSON exports
- Account reconciliation templates, items, owners, preparers, reviewers, materiality, risk, and workflow transitions
- DB-backed close periods, tasks, dependencies, blockers, readiness scoring, lock/reopen metadata
- Approval requests and certification metadata
- Evidence registry, requirements, checksum verification, coverage, and evidence links
- Journal policy flags and exception queue integration
- Intercompany import, reference matching, imbalance cases, and settlement metadata
- Control library, test plans, test results, remediation metadata
- Unified exception queue
- Governed metric snapshots and metric lineage
- Governed organization, legal-entity, branch, currency-reference, and non-overlapping fiscal-period metadata
- Hierarchical chart-of-accounts, accounting dimensions, journal definitions, balanced local ledger-control entries, validation/void metadata, and validated trial-balance aggregation

Common commands:

```bash
reconforge master-data organization-upsert --db output/reconforge.db --code SYN --name "Synthetic Group"
reconforge master-data entity-upsert --db output/reconforge.db --organization SYN --code US01 --name "Synthetic US" --currency USD
reconforge master-data period-upsert --db output/reconforge.db --name 2026-05 --start 2026-05-01 --end 2026-05-31

reconforge finance-core account-upsert --db output/reconforge.db --code 1010 --name "Cash at bank" --type Asset --normal-balance Debit
reconforge finance-core journal-upsert --db output/reconforge.db --code GJ --name "General Journal" --organization SYN --currency USD
reconforge finance-core entry-create --db output/reconforge.db --number JE/2026/0001 --organization SYN --entity US01 --period-id PER-... --journal GJ --date 2026-05-10 --description "Synthetic entry" --lines entry-lines.json
reconforge finance-core entry-validate --db output/reconforge.db --entry-id GLE-... --reason "Independent review completed"

reconforge accounts import-trial-balance --db output/reconforge.db --input output/trial_balance.csv --period 2026-05 --entity US01
reconforge accounts create-template --db output/reconforge.db --account-code 1000 --risk high --materiality 10000
reconforge accounts prepare --db output/reconforge.db --id AR-...
reconforge accounts submit --db output/reconforge.db --id AR-...
reconforge accounts review --db output/reconforge.db --id AR-... --reviewer reviewer
reconforge accounts complete --db output/reconforge.db --id AR-...

reconforge close period-init --db output/reconforge.db --period 2026-05 --start-date 2026-05-01 --end-date 2026-05-31
reconforge close task-status --db output/reconforge.db --task-id CT-... --status "In Progress"
reconforge close readiness --db output/reconforge.db --period-id CP-...

reconforge evidence register --db output/reconforge.db --file output/support.txt --object-type reconciliation --object-id AR-...
reconforge evidence coverage --db output/reconforge.db

reconforge journals import --db output/reconforge.db --input output/journals.csv
reconforge journals policy-run --db output/reconforge.db --period 2026-05 --period-end 2026-05-31

reconforge intercompany import --db output/reconforge.db --input output/intercompany.csv
reconforge intercompany match --db output/reconforge.db --period 2026-05

reconforge controls import-library --db output/reconforge.db --input output/controls.csv
reconforge controls plan-tests --db output/reconforge.db --period 2026-05

reconforge exceptions list --db output/reconforge.db
reconforge metrics compute --db output/reconforge.db --period 2026-05
```

Certification metadata is workflow metadata only. It is not a legal signature, audit sign-off, audit opinion, SOX/SOC/ISO certification, or compliance conclusion.

Evidence integrity is checksum/provenance support only. It is not a signature workflow or non-repudiation control.

Known limits:

- These are foundations for local pilots, not a complete enterprise close suite.
- Workflows rely on local users/RBAC when actions are performed by known usernames.
- Direct ERP connectors, SSO, SCIM, cloud backup, SaaS hosting, and compliance certification are not implemented.
