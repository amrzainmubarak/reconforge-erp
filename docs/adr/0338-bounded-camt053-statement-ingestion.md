# ADR 0338: Add a bounded CAMT.053 statement ingestion boundary

- Status: accepted
- Date: 2026-08-05
- Scope: `P4-CON-001`, `P4-PLAT-001`

## Decision

Add an offline, read-only ISO 20022 CAMT.053 parser for one customer statement
document. The parser accepts one `BkToCstmrStmt/Stmt`, uses `defusedxml`, caps
the input at 8 MiB and 100,000 entries, requires a stable `NtryRef` or
`AcctSvcrRef` identity, validates finite Decimal amounts and dates, preserves
credit/debit direction, and emits a closed replayable JSON artifact. A CLI
command, `reconforge connectors parse-camt053`, exposes the same contract.

## Rationale

CAMT.053 is an open banking statement format and gives ReconForge a concrete
banking-pack ingestion boundary without inventing vendor credentials or
claiming live bank interoperability. Exact amounts, stable identity, XML
entity-expansion rejection, and deterministic source digests are safer than a
generic permissive XML importer.

## Evidence boundary

This slice proves synthetic CAMT.053 parsing and artifact replay only. It does
not prove any bank's dialect, certificate/credential lifecycle, network
connector operation, payment initiation, settlement semantics, statutory
posting, or write-back. Unknown bank extensions remain an explicit future
conformance profile rather than being silently ignored.

## Rollback

Remove the parser, CLI command, fixture, schema, ADR, manifest entries, and
execution records. Existing provider-neutral reference connectors and
write-back boundaries remain unchanged.
