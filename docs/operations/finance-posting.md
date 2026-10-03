# Reviewed Manual posting and recovery

This experimental operational contract requires SQLite48 or PostgreSQL0098.
Its effects are separate from historical Draft/Validated control entries.
An existing Validated control entry without verified preparer/reviewer evidence
cannot be adopted by changing its status or supplying a username label.

Configure the organization, legal entity, fiscal period, journal, posting
accounts and required dimensions through the existing Finance/master-data
administration. The local database must already be migrated. Create individual
stored users with the required permissions. The preparer needs manage; an
independent reviewer needs validate; posting needs post. Reversal preparation
needs manage and reverse, and posting that reversal also requires reverse.
The authenticated preparer alone may replace their Draft content.

## Local command flow

Every command requests the stored user's password through a hidden prompt.
No password, actor identity or session-assurance flag is accepted in argv.
The following synthetic example assumes SYN/EG01, journalGJ, accounts1010/3000
and dimensionCC/HQ are configured. Replace the fiscal-period ID with its actual
stored ID. The journal supplies the captured currency; omit currency_code.

```json
{
  "entry_number": "MANUAL-001",
  "organization_code": "SYN",
  "entity_code": "EG01",
  "period_id": "the-existing-period-id",
  "journal_code": "GJ",
  "posting_date": "2026-07-05",
  "description": "Synthetic opening funding",
  "lines": [
    {"account_code": "1010", "debit": "1000.00", "dimensions": {"CC": "HQ"}},
    {"account_code": "3000", "credit": "1000.00", "dimensions": {"CC": "HQ"}}
  ]
}
```

Save it as a regular JSON file under oneMiB. Monetary input is exact decimal
text and must match the journal's retained policy.

```text
reconforge finance-core posting draft --db local.db --username maker --input entry.json
reconforge finance-core posting review --db local.db --username checker --entry-id ENTRY_ID --reason "Independent content review"
reconforge finance-core posting preview --db local.db --username checker --entry-id ENTRY_ID
reconforge finance-core posting post --db local.db --username checker --entry-id ENTRY_ID --command-id UNIQUE_COMMAND_ID --expected-validation-digest REVIEW_DIGEST --reason "Explicit reviewed posting"
reconforge finance-core posting effect --db local.db --username checker --effect-id EFFECT_ID
```

Use the entry ID and validation_digest returned by the actual commands.
Review preserves canonical snapshot_json and exact minor-unit display strings.
Verify the original canonical text; parsing large amounts as JavaScript Number
and reserializing changes financial evidence beyond its exact integer range.

For an uncertain post acknowledgement, retry exactly the original command ID,
actor, entry, digest and reason. A changed request conflicts. Read-back verifies
the authoritative effect and exact audit/outbox affinity before reporting
success. Local storage rejection exits1 without acknowledging a partial effect.

## Correction and balances

```text
reconforge finance-core posting reverse --db local.db --username maker --effect-id EFFECT_ID --command-id UNIQUE_REVERSAL_COMMAND --entry-number REV-001 --period-id PERIOD_ID --date 2026-07-06 --reason "Full correction"
```

This prepares a Draft. An independent user must review it and explicitly post
it using the preceding commands. It copies original scope and monetary policy
and exactly inverts every line and dimension. The original effect remains
immutable. A reversal cannot itself be reversed under this first contract.

```text
reconforge finance-core posting trial-balance --db local.db --username checker --period-id PERIOD_ID --organization SYN --entity EG01
```

balance_scope is selected-period-net-activity. turnover_totals retain all
contributing debits/credits; balance_totals sum net account debits/credits.
A same-period full reversal gives zero net activity while both effects and
positive turnover remain. Earlier periods/opening balances are not included.
Each contributing amount has effect, entry and line drill-down. Mixed retained
monetary policies are rejected rather than silently combined.

The additive business-date report is available separately:

```text
reconforge finance-core posting balances-as-of --db local.db --username checker --period-id PERIOD_ID --organization SYN --entity EG01 --as-of-date 2026-07-15
```

Its contract finance-posted-balances-v1 reports opening before the selected
period, activity through the inclusive cutoff, and cumulative closing. Read
balance_scope=recorded-postings-business-date-as-of and retain report_digest.
The server GET /api/v1/finance-core/posted-balances-as-of uses the same selected
scope and exposes exact monetary strings plus canonical report_json. Every
contribution retains its effect, source entry, period, business date and line.
Compatible retained money policy is required across all contributing periods.

This reads currently recorded immutable postings: a later backdated posting can
change a newly produced report for the same cutoff. It does not reconstruct
what was known at an earlier timestamp or import an opening balance. Limits are
1000 effects,10000 lines and2MiB combined snapshots/final canonical report;
excess evidence is rejected before the remaining effects are loaded. Retain
verified report artifacts when comparing runs. See ADR0817 for the boundary.

## Server and recovery

The PostgreSQL profile exposes preview, explicit post, effect GET, reversal
preparation and posted-trial-balance under /api/v1/finance-core. Closed request
schemas reject actor/assurance input. Human identity, recent configured session
method, current authority, canonical scope and cookie CSRF are rechecked.
SQLite HTTP posting awaits its own recent-session assurance adapter; the local
password-bound commands are implemented.

Standalone SQLite writes own BEGIN IMMEDIATE and refuse pending caller work.
Library composition must use SQLiteFinancePostingUnitOfWork explicitly; a
caught child failure makes the complete unit rollback-only. PostgreSQL requires
READ COMMITTED and preserves the caller's transaction and established scope.

Backups retain provenance, effects, commands and their linked evidence. Restore
verifies an unpublished temporary database before publication; export uses a
consistent read snapshot while preserving an existing caller transaction.
Populated downgrade refuses to discard effects, commands or any retained
provenance. A rollback requires a compatible pre-upgrade backup and reconciliation
of subsequent writes; removing guards reinstates demonstrated weaker controls.

Reproduce the actual lifecycle locally with tests/test_finance_posting_cli.py
and tests/test_sqlite_finance_posting.py. PostgreSQL acceptance needs a synthetic
administrator capable of creating/deleting isolated test databases, a restricted
nonowner application role, and matching native dump/restore tools. Run the
posting, concurrency, API and restore modules recorded in ADR0811. The retained
FINANCE_POSTING_2026-10-03.json reports exact scopes, source hashes and failures.
This contract does not automatically post stock, AR, AP or cash into GL.
