# Finance Core Control Ledger

ReconForge includes an experimental local foundation for charts of accounts, hierarchical financial accounts, analytic dimensions, finance journal definitions, balanced multi-line entries, validation/void metadata, a validated trial-balance view, and a deterministic multi-entity currency-translation artifact. The ledger is backed by SQLite migration 8 and the bounded translation artifact is part of the `finance.core` runtime module without adding a database migration.

This is a finance-control ledger and calculation foundation for local review and future module integration. The translation slice verifies balanced source trial balances, explicit rates, account mapping, rounding, and an unposted translation-adjustment proposal. It does not post to a source ERP, replace a statutory general ledger, execute payments, calculate tax, perform ownership/elimination/statutory consolidation, certify financial statements, or provide audit/legal assurance.

## Initialize or upgrade

```bash
reconforge db backup --db output/reconforge.db --output output/pre-v8-backup
reconforge db migrate --db output/reconforge.db
reconforge modules show finance.core
reconforge modules validate
```

Migration 8 is additive. Existing `accounts` rows are preserved, assigned to a generated `DEFAULT` chart for their workspace, and given conservative defaults for account type and posting flags. Existing export-based `journal_entries` keep their original policy-control meaning; they are not silently converted into balanced ledger entries.

Restore uses the backup's source schema first and then applies current migrations. A rollback is therefore restore-based: verify and retain the pre-migration local backup before an important upgrade.

## Configure finance masters

Create organization, entity, and period references first:

```bash
reconforge master-data organization-upsert --db output/reconforge.db --code SYN --name "Synthetic Group"
reconforge master-data entity-upsert --db output/reconforge.db --organization SYN --code EG01 --name "Synthetic Egypt" --currency EGP
reconforge master-data period-upsert --db output/reconforge.db --name 2026-07 --start 2026-07-01 --end 2026-07-31
```

Then configure the chart, accounts, required cost center, and journal:

```bash
reconforge finance-core chart-upsert --db output/reconforge.db --code DEFAULT --name "Synthetic Chart"
reconforge finance-core account-upsert --db output/reconforge.db --code 1010 --name "Cash at bank" --type Asset --normal-balance Debit
reconforge finance-core account-upsert --db output/reconforge.db --code 3000 --name "Opening equity" --type Equity --normal-balance Credit
reconforge finance-core dimension-upsert --db output/reconforge.db --code CC --name "Cost Center" --type "Cost Center" --required
reconforge finance-core dimension-value-upsert --db output/reconforge.db --dimension CC --code HQ --name "Head Office"
reconforge finance-core journal-upsert --db output/reconforge.db --code GJ --name "General Journal" --organization SYN --currency EGP
```

## Create and validate an entry

Save the lines in a user-selected local JSON file. Amounts are strings so decimal precision is not lost through binary floating-point conversion:

```json
{
  "lines": [
    {
      "account_code": "1010",
      "debit": "1000.00",
      "dimensions": {"CC": "HQ"}
    },
    {
      "account_code": "3000",
      "credit": "1000.00",
      "dimensions": {"CC": "HQ"}
    }
  ]
}
```

Use the fiscal-period identifier printed by `master-data period-upsert`:

```bash
reconforge finance-core entry-create \
  --db output/reconforge.db \
  --number JE/2026/0001 \
  --organization SYN \
  --entity EG01 \
  --period-id PER-... \
  --journal GJ \
  --date 2026-07-05 \
  --description "Synthetic balanced entry" \
  --lines entry-lines.json

reconforge finance-core entry-validate --db output/reconforge.db --entry-id GLE-... --reason "Independent review completed"
reconforge finance-core trial-balance --db output/reconforge.db --period-id PER-... --organization SYN --entity EG01
```

Validation is local workflow metadata. It does not post the entry elsewhere. A Validated entry can be moved only to Voided, with a reason; its lines and dimension links remain immutable.

Migration 11's [FIFO inventory valuation](inventory-valuation.md) can prepare a balanced Generated entry in this ledger. Migration 12's exact valuation reversal copies the original accounts and dimension links and swaps every debit and credit into a second Generated entry. Both bridges always create status `Draft`; valuation or reversal approval does not call Finance Core validation or confer `finance_core.validate`. If required analytic dimensions exist, valuation policy setup/approval fails until an explicit mapping is available rather than fabricating dimension values. An Approved reversal protects its mirror Finance entry, lines, and dimensions from later voiding or silent mutation.

## Deterministic controls

- Amounts are converted from exact decimal strings to integer currency minor units.
- Each line contains exactly one non-zero debit or credit.
- An entry contains 2–1,000 lines and total debit must equal total credit above zero.
- The posting date must fall inside an `Open` fiscal period.
- Organization, legal entity, journal, chart, currency, account, and dimension relationships are verified.
- New account hierarchies reject self-parenting and recursive cycles.
- Required active dimensions must appear on every line.
- Posting-disabled, manual-posting-disabled, and inactive accounts are rejected where applicable.
- Draft persistence and validation recheck their references inside one SQLite write transaction.
- Referenced chart organization scope and journal chart/currency scope cannot be rewritten.
- SQLite triggers independently require balanced validation metadata and protect Validated/Voided headers, lines, dimensions, and review metadata from mutation.
- When the actor is a known local user, the creator cannot validate the same entry.
- Mutations append sanitized events to the local audit hash chain.

## Permissions

| Permission | Default roles | Scope |
| --- | --- | --- |
| `finance_core.read` | admin, controller, preparer, reviewer, auditor-readonly | Read masters, entries, summary, snapshot, and trial balance |
| `finance_core.manage` | admin, controller, preparer | Manage finance masters and Draft entries |
| `finance_core.validate` | admin, controller, reviewer | Validate or void entries, subject to creator/reviewer SoD |

Trusted labels such as `local-cli` retain single-user local compatibility. SoD enforcement applies when the actor resolves to a stored local user.

## Local contracts

- `docs/schemas/ledger_entry_lines.schema.json`: CLI line input.
- `docs/schemas/finance_core_snapshot.schema.json`: bounded, path-free snapshot.
- `docs/schemas/ledger_control_trial_balance.schema.json`: validated trial-balance response.
- `docs/schemas/consolidation-translation-result-v1.schema.json`: replay-verifiable multi-entity translation result with an explicitly unposted CTA proposal.

The translation contract and limitations are documented in
[`docs/consolidation-translation.md`](consolidation-translation.md) and ADR 0210.

```bash
reconforge finance-core summary --db output/reconforge.db
reconforge finance-core snapshot --db output/reconforge.db > finance-core-snapshot.json
```

Snapshots omit database paths, local evidence paths, credentials, sessions, and source-export locations. List commands default to 500 rows and accept bounded `--limit` and `--offset` values.

## Authenticated API

The default API profile uses the local SQLite Finance Core service. The
explicit PostgreSQL server profile routes bounded account, posted-entry, and
organization/fiscal-period trial-balance operations to the PostgreSQL
ledger-control repository. Server mode is
tenant-scoped rather than workspace-scoped: account writes require
`organization_code`, and entry writes require `organization_code` plus
`currency_code` (or an organization base currency). Entity, journal, dimension,
chart hierarchy, draft-validation, and void semantics are not silently
discarded; those capabilities return HTTP `501` until their PostgreSQL
schema/workflow slices are implemented. Trial balance supports organization
plus fiscal-period aggregation; legal-entity scoping remains unsupported
because the bounded server ledger has no entity dimension.

Read routes:

- `GET /api/v1/finance-core/summary`
- `GET /api/v1/finance-core/snapshot`
- `GET /api/v1/finance-core/charts`
- `GET /api/v1/finance-core/accounts`
- `GET /api/v1/finance-core/dimensions`
- `GET /api/v1/finance-core/dimension-values`
- `GET /api/v1/finance-core/journals`
- `GET /api/v1/finance-core/entries`
- `GET /api/v1/finance-core/entries/{entry_id}`
- `GET /api/v1/finance-core/trial-balance`

Mutation routes:

- `POST /api/v1/finance-core/charts`
- `POST /api/v1/finance-core/accounts`
- `POST /api/v1/finance-core/dimensions`
- `POST /api/v1/finance-core/dimension-values`
- `POST /api/v1/finance-core/journals`
- `POST /api/v1/finance-core/entries`
- `POST /api/v1/finance-core/entries/{entry_id}/validate`
- `POST /api/v1/finance-core/entries/{entry_id}/void`

Request objects reject unknown fields. API pages default to 500 records, cap at 1,000, and include applied pagination metadata.

## Current limitations

- One workspace-level account code remains unique for backward compatibility, even when more than one chart is defined.
- Entry currency must match both the journal and legal-entity currency. The separate translation artifact has explicit rate provenance, but it does not remeasure or mutate Finance Core entries.
- Entry numbering is user/import supplied and unique per workspace; governed numbering sequences are planned.
- Trial balance includes Validated local control entries only. It is not a balance sheet, P&L, cash-flow statement, or statutory ledger report.
- AR, AP, tax, assets, budgets, bank execution, period-end remeasurement, ownership/elimination consolidation, statutory statements, and source-ERP writeback remain separate future slices.
- FIFO valuation and exact whole-valuation reversal can prepare balanced Drafts, but AVCO/landed/manufacturing costing, automatic validation, partial or reversal-of-reversal orchestration remain separate future slices.
