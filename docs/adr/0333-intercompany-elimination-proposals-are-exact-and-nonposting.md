# ADR 0333: Intercompany elimination proposals are exact and non-posting

## Status

Accepted — 2026-08-05

## Context

The intercompany workflow can import and match signed transactions, while the
consolidation worksheet accepts explicit source-bound elimination lines. There
was no deterministic bridge between those boundaries. Inferring group accounts,
FX, tax, or statutory treatment would make a financial effect look complete
without sufficient evidence.

## Decision

Add `intercompany-elimination-v1` as a pure application/domain boundary and a
read-only `reconforge consolidation intercompany-eliminations` command. The
caller must provide a signed source amount in the reporting currency, an
explicit group-account mapping, account type, entity/counterparty, period,
reference, and source digest for every line.

A group is proposed only when its explicit reference/period/currency partition
has reciprocal entity coverage and its signed Decimal total is exactly zero.
The generated elimination negates each source line, preserves entity/account
type/source digest lineage, and is marked `intercompany_transaction`. Every
imbalanced, one-way, or insufficient group is retained as `unresolved` with a
reason; it is never rounded, converted, dropped, or posted.

The result carries request, source-group, and result digests and can be replayed
against the original typed source lines. The JSON schema is closed and the
command performs no database mutation, network call, provider write-back, or
ledger/statutory posting.

## Consequences

The owner/team can prepare a reproducible elimination evidence artifact and
feed approved proposals into the existing consolidation worksheet boundary.
This closes only the deterministic source-to-proposal bridge. It does not
decide accounting standards, acquisition/tax/FX policy, account mappings,
statutory/legal-book posting, intercompany settlement, or live ERP/bank
write-back.

## Rollback

Remove the CLI command and application import while retaining existing
intercompany matching and consolidation worksheet contracts. No stored source
transactions or journals are modified by this slice.

## Verification

```bash
uv run pytest tests/test_intercompany_elimination.py -q
uv run python -m ruff check reconforge/domain/intercompany_elimination.py reconforge/application/intercompany_elimination.py
uv run python -m mypy reconforge/domain/intercompany_elimination.py reconforge/application/intercompany_elimination.py
```
