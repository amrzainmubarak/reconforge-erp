# ADR 0844: Extend conserved operations with source-owned financial cycles

Status: accepted for implementation, capability acceptance pending integration gates.
Date: 2026-10-09.
Base: PR127 `34b9e7a5b2a7c4d8ae49b641a36de030a878d507`, retaining PR126/125/124.

## Decision

Retain the modular monolith, existing native AR/AP, receipt valuation, posting,
currency registry, authority and immutable evidence engines. Implement three
independent PostgreSQL source owners with central route, posting and migration
integration:

| Owner | First complete cycle | File ownership | Forward revision |
| --- | --- | --- | --- |
| CA1 commercial collections | Prepare, independently review and post partial cash allocation inside one stock-sales AR invoice | New commercial collection owner, stock commerce projection, commercial UI and tests | `0120_pg_commercial_collections` |
| LC1 landed cost | Allocate paid freight/duties before receiving; publish goods, initial FIFO cost and linked cash/GL atomically | New landed-cost owner, procurement receiving integration, procurement UI and tests | `0121_pg_landed_cost` |
| FA1 fixed assets | Reviewed acquisition, exact cumulative straight-line depreciation and disposal | New asset owner, asset UI and tests | `0122_pg_fixed_assets` |

Each owner requires current scoped authority, three independent persisted human
identities, immutable preparation and command receipts, exact minor-unit amounts,
native financial effects, audit/outbox and deferred SQL closure. Business source
effects and source-owned entries cannot post or reverse through generic entry
routes. No duplicate ledger, currency implementation or new infrastructure is
introduced. Root owns shared posting admission, application registration,
authorization inventory, schema installation, Studio navigation and CI.

Migration dependency order is CA1 -> LC1 -> FA1; capability execution is parallel.
Forward function wrappers must preserve other admitted owners and frozen legacy
contracts. Existing full receipt, AP installment and historical FIFO contracts
remain valid. Landed cost is prepaid cost at initial receipt publication, not an
in-place rewrite of published layers or freight supplier AP. Asset scope is
functional currency and configured accounts, not global statutory asset/tax rules.

## Evidence and limits

The accepted PR127 CI supplies the baseline; it is not rerun before implementation.
Owners run targeted gates after cohesive batches. Integrated acceptance runs on
fixed committed source, including actual authenticated Studio writes, native
PostgreSQL nonowner roles, concurrency, SQL bypass, restore and old regressions.
Benchmark changes preserve raw observations, workload/source identity, failures
and measured resource scope. No accepted old packet is overwritten.

Real operational FX requires a governed transaction-currency subledger absent in
the current functional-currency posting contract. It is deferred rather than
mislabeling reconciliation FX adjustments as operational foreign-currency GL.
Customer/supplier financial inverses must restore their frozen original quantity,
cost, revenue and settlement consequences before being called complete.

## Rollback

Keep the PR stack unmerged. Downgrade new owners only when their protected source
tables are empty; otherwise preserve history and restore a verified pre-upgrade
backup to an isolated target. Never delete posted financial effects for rollback.
