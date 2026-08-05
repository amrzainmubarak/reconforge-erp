# CAMT.053 bounded read-only statement input

ReconForge includes an offline parser for one ISO 20022 `camt.053` customer
statement document. Run it with:

```powershell
reconforge connectors parse-camt053 statement.xml --output statement.json
```

The parser is deliberately bounded:

- one `BkToCstmrStmt/Stmt` document;
- 8 MiB input and 100,000 entries maximum;
- `defusedxml` entity-expansion protection;
- finite Decimal amounts with explicit `CRDT`/`DBIT` direction;
- booking and value dates with value-date ordering;
- stable `NtryRef` or `AcctSvcrRef` identity, rejecting duplicates or missing identity;
- optional opening/closing balances and transaction references;
- deterministic `source_digest` over the normalized artifact.

This is a local file boundary, not a live bank connector. Bank-specific dialects,
network credentials, certificates, payment initiation, settlement, posting, and
write-back require separately approved conformance profiles and runtime evidence.
