# ADR 0211: Consolidation ownership is effective-dated and worksheets do not post

- Status: Accepted
- Date: 2026-08-01
- Owners: Financial Integrity / Platform Architecture

## Context

ADR 0210 established deterministic multi-entity currency translation, but it
deliberately omitted ownership, eliminations, and non-controlling interest
(NCI). Applying percentages without effective dates, graph validation, source
lineage, or a precise presentation policy would create results that cannot be
reproduced or defended. Treating a calculated worksheet as a posted journal
would also bypass approval, period, reversal, and ledger controls that do not
yet exist for consolidation.

## Decision

1. Worksheet v1 accepts only the verified translation-result v1 artifact. The
   complete translation input remains embedded in the closed request so replay
   can reject rehashed output tampering.
2. Direct ownership is an exact finite `Decimal` in `(0, 1]`, with source
   digest, semantic version, effective-from/effective-to dates, preparer,
   different approver, and approval timestamp. Approval cannot postdate
   worksheet preparation.
3. Full-consolidation v1 requires every active direct interest to exceed 50%.
   Historical intervals for one subsidiary may not overlap. On the reporting
   date every translated entity except the declared root has exactly one active
   parent; the graph must be acyclic and rooted at that parent.
4. Effective group ownership is the exact product of direct interests along the
   root-to-entity path. The non-controlling percentage is `1 - effective` and
   both the path and active interest IDs remain in the artifact.
5. NCI v1 is explicitly a presentation allocation, not acquisition accounting
   or a journal. It reports the non-controlling share of translated net assets
   (`Asset + Liability` signed balances) and current-period profit
   (`-(Income + Expense)`), retaining unrounded values and currency-policy
   rounding deltas.
6. Every elimination is a versioned proposal with at least two entities,
   non-zero reporting-currency Money lines, source references and SHA-256
   digests, a rationale, and an exact zero balance. Account-type conflicts,
   unknown entities/currencies, duplicate line IDs, and non-zero proposals fail
   closed. Elimination preparation cannot postdate worksheet preparation.
7. The worksheet includes the unposted translation adjustment needed to make
   translated balances balance, applies only balanced elimination proposals,
   and must remain zero before and after elimination.
8. Canonical ordering covers ownership histories, paths, elimination lines,
   accounts, and output arrays. Request/result digests and the deterministic
   worksheet ID are permutation-stable.
9. `posting_effect` is always `none`; NCI and eliminations are always
   `posted=false`. Journal creation, maker-checker lifecycle, period locks,
   posting, reversal, and SQLite/PostgreSQL run persistence are later slices of
   `P4-FIN-002`.

## Consequences

- The project can now reproduce a bounded ownership/NCI/elimination worksheet
  without silently selecting ownership or mutating a ledger.
- Indirect ownership is visible and exact, while unsupported acquisition,
  goodwill, equity-method, ownership-change, and FX-recycling policies remain
  explicit gaps.
- The ownership preparer/approver fields are validated artifact facts; they do
  not yet prove identity-provider assurance or a persisted approval workflow.
- The result is a consolidated control worksheet/trial balance, not a balance
  sheet, income statement, statutory consolidation, audit opinion, or source
  ERP posting.

## Rollback

Remove the optional lifecycle domain file, application method, schema, tests,
module metadata, and documentation. This slice adds no migration, database row,
network call, journal, source write, tag, release, or deployment effect.
