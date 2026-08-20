# ADR 0283: PostgreSQL PPA evidence is immutable and non-posting

## Status

Accepted for the bounded Phase 4 consolidation persistence slice.

## Context

The acquisition fair-value bridge and purchase-price allocation (PPA) are
deterministic, source-bound, maker-checker artifacts, but they previously
existed only as local calculation/CLI results. Losing the artifact at the
server boundary would break replayable close evidence, while persisting a
journal would overstate the domain's statutory scope.

## Decision

Add application service `AcquisitionPpaApplicationService` and PostgreSQL
adapter `PostgresConsolidationPpaRepository`. Migration
`0060_pg_consolidation_ppa` stores the canonical request/result JSON, both
digests, acquisition/period identity, reporting currency, and maker-checker
attribution under forced tenant RLS. The adapter recomputes the PPA, verifies
the result digest and `posted: false`, accepts identical retries, and appends a
domain-audit event in the same transaction.

## Safety boundary

- The table is an evidence store only. It cannot post journals, decide tax,
  deferred tax, impairment, equity-method treatment, or statutory statements.
- Update and delete are database-rejected; downgrade refuses while evidence
  exists. A tenant cannot read a sibling tenant's artifact under RLS.
- No ERP/bank connector, write-back, valuation provider, live rate, or external
  assurance claim is introduced. Runtime evidence is synthetic PostgreSQL on a
  single CI node.

## Rollback

The downgrade first checks for rows and fails closed with a data-loss message.
After a governed retention decision and an empty table, it removes the trigger,
function, index, and table without rewriting prior close or ledger records.
