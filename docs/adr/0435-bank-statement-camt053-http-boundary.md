# ADR 0435: Add a governed CAMT.053 HTTPS statement boundary

- Status: accepted
- Date: 2026-08-07
- Scope: `P4-CON-001`, `connectors.boundary`

## Decision

Add `bank-statement-camt053-readonly`, a read-only network connector that uses
the existing `NetworkConnectorExecutor` and then parses one response with the
bounded `parse_camt053_bytes` contract. The endpoint path is exact, credentials
are runtime secret references, responses are capped at the parser limit, and an
optional expected account guard prevents a response for another account from
being accepted. The adapter returns request, raw-response, and normalized-source
digests but has no write or posting capability.

## Rationale

This closes a useful banking-pack vertical slice without inventing a bank's
authentication or dialect. Reusing the tested parser keeps Decimal, identity,
date, XML entity-expansion, and statement-cardinality invariants in one place.

## Evidence boundary

Synthetic transport tests prove endpoint hardening, secret isolation, account
scoping, malformed-response refusal, and digest propagation. They do not prove
provider interoperability, source authenticity, certificate rotation, bank
availability, settlement, payment initiation, ERP mapping, posting,
write-back, or production readiness.

## Rollback

Remove the adapter, tests, documentation, manifest entries, and execution
records. The offline CAMT.053 parser and provider-neutral network executor
remain unchanged.
