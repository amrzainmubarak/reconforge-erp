# Monetary-policy upgrade and compatibility contract

This contract applies to SQLite migration 47 and PostgreSQL
`0094_pg_finance_policy`. It changes monetary interpretation safeguards; it does
not turn the existing Finance Core control ledger into a complete operational GL.

## Persisted behavior

New Finance Core entries and inventory valuation documents capture currency
precision, rounding policy, registry version and snapshot digest in their write
transaction. Draft edits, exact reads, validation, trial balances, generated
valuation GL entries and reversals use the retained policy. FIFO consumes only
layers whose source policy is verified and compatible with the target document.
Changing installed currency definitions or a workspace registry binding cannot
silently reinterpret those amounts.

Currency code and precision, and entity functional currency, are immutable after
creation. Name and active metadata remain editable. This is a deliberate change
even for unused currencies; a future governed policy-transition operation must
make any economic reinterpretation explicit.

## Existing data

Upgrade adds nullable metadata without rescaling amounts or inventing historical
provenance. Old rows retain raw minor units and identities. Raw entry listing is
available for review, but formatted reads, trial balances containing unverified
entries, and financial mutations requiring interpretation fail with
`finance_currency_policy_unverified`. Old valuation source layers also fail
closed when a new FIFO approval would otherwise consume unverified values.

Preserve the original registry configuration, source exports and signed-off
amounts needed for historical review. There is no automatic attestation or repair
endpoint in this slice. Assigning today's digest to an old row would not prove
its historical policy and is not an upgrade procedure. Sites with material
legacy records must evaluate these changed read/mutation contracts against a
restored copy before upgrading a live service.

## Upgrade and restore sequence

1. Record the current schema/application version and verify a complete backup
   using the existing backup/restore runbook. Retain source registry evidence.
2. Apply the normal supported migration command to an isolated restore. Inspect
   the count of wholly unverified records and exercise required reporting flows.
3. Verify a new synthetic balanced entry, retained policy across a registry
   change, valuation/reversal behavior and a fresh restore. Use a nonowner
   application role for normal operations and separate migration credentials.
4. Release acceptance still requires full regression, artifact validation and
   the deployment's ordinary upgrade process. The implementation here has not
   performed a production upgrade or copied customer data.

SQLite logical backup formats 46 and 47 remain readable. Restore imports retained
legacy NULL policy only inside its unpublished temporary database, reinstates
new-insert guards, migrates and checks relationships plus captured snapshot
bindings before publishing the restored file. New application writes cannot
use this temporary compatibility path.

## Rollback

PostgreSQL downgrade locks both policy-bearing tables and refuses when captured
policy exists in either. Empty or wholly unverified legacy states can replay
downgrade/upgrade. Once new policy-bound writes exist, an operational rollback
requires a verified earlier backup and explicit preservation/reconciliation of
subsequent writes; dropping policy columns is not a safe shortcut. SQLite uses
the existing verified restore procedure.

[ADR 0792](../adr/0792-captured-finance-currency-policy.md) records the decision.
[Focused evidence](../execution/FINANCE_POLICY_2026-10-03.json) records the tested
scope and prerequisites; separate native PostgreSQL 16/17 restore reports verify
the migration chain through 0094. These synthetic results do not establish
customer outcomes or complete nested workspace/entity transaction isolation.
