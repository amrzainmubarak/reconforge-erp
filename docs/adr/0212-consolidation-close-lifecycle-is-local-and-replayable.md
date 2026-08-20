# ADR 0212: Consolidation close lifecycle is local and replayable

- Status: Accepted
- Date: 2026-08-01
- Owners: Financial Integrity / Platform Architecture

## Context

ADR 0211 made ownership, NCI presentation, and eliminations replayable, but it
kept every worksheet non-posting. The next risk is allowing a calculated
worksheet to look final without maker-checker, immutable effect, reversal,
period, backup, and restore controls. A premature statutory ledger or ERP
write-back would also expand the product beyond the evidence available in this
repository.

## Decision

1. Migration 25 adds a local SQLite consolidation close lifecycle for verified
   worksheet v1 artifacts only.
2. The lifecycle is `Prepared -> Approved -> Posted -> ReversalPrepared ->
   Reversed`. Each transition uses optimistic row versions and actor/reason/
   timestamp evidence.
3. Preparation persists the bounded worksheet payload, result digest, and exact
   balanced journal lines derived from approved zero-sum eliminations. The
   database and reader replay the worksheet before public use.
4. Approval requires an actor independent of preparation. Posting requires an
   actor independent of both preparation and approval. Reversal approval
   requires an actor independent of reversal request and posting.
5. `Posted` means an immutable balanced effect in ReconForge's local
   consolidation control journal only. It does not create Finance Core entries,
   statutory books, source-ERP postings, payments, tax effects, or statements.
6. Reversal creates a second committed effect whose lines exactly negate the
   posting effect. The original effect is not edited or deleted.
7. Period locks require at least one final governed run whose preparation
   predates the lock and no unfinished run at that time. Reopen requires an
   independent actor and an immutable period event. Re-lock after reopen
   records another event rather than overwriting the historical transition log.
8. Local backup includes all consolidation lifecycle tables. Restore replays
   run transitions, effects, and period events through the installed schema
   triggers, then re-verifies worksheet and effect integrity before replacing
   the target database.

## Consequences

- P4-FIN-002 now has a persisted local journal/period lifecycle foundation
  with exact minor-unit balance, maker-checker, reversal, lock/reopen, and
  restore evidence.
- The slice remains a local SQLite/library boundary. There is no API, CLI, UI,
  PostgreSQL parity adapter, statutory statement, acquisition-accounting model,
  live rate provider, connector, or write-back path.
- Trusted local actor labels are attributable operator labels, not federated
  identity assurance. Enterprise identity and ABAC remain later work.
- Backup SHA-256 and replay verification protect local structural integrity,
  not publisher authentication, legal retention, host-loss DR, or independent
  assurance.

## Rollback

Take and verify a local backup before applying migration 25. Operational
rollback is restore-based because SQLite migrations are forward-only. To revert
the feature in source, remove the migration, repository/application boundary,
bounded worksheet JSON profile, tests, module metadata, ADR, and operator docs.
No production system, source ERP, tag, release, or deployed service rollback is
part of this slice.
