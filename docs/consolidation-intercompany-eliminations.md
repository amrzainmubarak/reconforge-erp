# Intercompany elimination evidence v1

`intercompany-elimination-v1` converts explicitly mapped, signed intercompany
source lines into non-posting consolidation elimination proposals. It is a
controlled evidence bridge, not an accounting-standard engine.

## Input contract

Each line must include:

- transaction ID, period, entity, counterparty, and explicit reference;
- group account code and account type supplied by the owner/team mapping;
- exact `Money` in the declared reporting currency;
- source reference and lowercase SHA-256 source digest.

The builder partitions by period, reference, and currency. It rejects any line
whose currency differs from the reporting currency; it never performs an
implicit FX conversion.

## Proposal and unresolved behavior

An exact proposal is emitted only when the partition has at least two entities,
the entity and counterparty sets are equal, and the signed Decimal total is
exactly zero. The proposal contains the negated source amounts, preserving the
source entity, mapped group account, account type, source digest, and a stable
line ID. The proposal is suitable as explicit input to the existing
`ConsolidationElimination` contract, where worksheet-level group membership and
zero balance are checked again.

One-way, incomplete, or imbalanced partitions remain in the result as
`unresolved` with a reason. No tolerance, rounding, account inference, tax,
FX, or statutory conclusion is applied.

## Replay and operation

The output is closed by
`docs/schemas/intercompany-elimination-v1.schema.json`. `request_digest` binds
the typed source lines and policy inputs; `source_group_digest` binds each
partition; `result_digest` binds the complete output. Replaying with
`verify_intercompany_elimination_payload` requires the original typed source
lines and rejects tampered output.

The read-only operator path is:

```bash
reconforge consolidation intercompany-eliminations --input request.json
```

The command performs no database write, provider call, network egress, ledger
posting, or write-back. Approval, statutory/legal-book treatment, live ERP/bank
semantics, and PostgreSQL persistence remain later bounded work.
