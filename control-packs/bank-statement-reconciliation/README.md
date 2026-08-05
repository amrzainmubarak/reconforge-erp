# Bank Statement Reconciliation Controls

This local, read-only pack identifies missing bank-to-ledger references,
duplicate ledger identities, and amount variances. It complements the typed
CAMT.053 control at `reconforge bank statement control-run`.

It is not a bank connector, payment system, fraud engine, statutory ledger, or
automatic journal/write-back path.

```bash
reconforge rules run --input examples/bank_statement_control/csv --pack control-packs/bank-statement-reconciliation --output output/bank-pack
reconforge bank statement control-run --statement-input examples/bank_statement_control/statement.xml --ledger-input examples/bank_statement_control/ledger.json --currency EUR --output output/bank-statement-control/report.json
```
