# ADR 0005: Finance Core Uses A Separate Local Control Ledger

- Status: Accepted
- Date: 2026-07-22

## Context

ReconForge already stores `journal_entries` imported from local CSV/JSON exports for deterministic policy checks. Each row represents an exported control record and is unique by source journal ID. Changing that table into a multi-line double-entry journal would break existing CLI behavior, tests, demos, and evidence lineage.

The platform also needs credible finance primitives—governed account hierarchy, dimensions, journal definitions, exact amounts, balanced entries, review separation, immutability, and trial-balance aggregation—before AR/AP, budgets, assets, or financial statements can be implemented honestly.

## Decision

1. Add migration 8 without changing the meaning of the existing export-control tables.
2. Extend existing `accounts` additively and assign legacy rows to a deterministic workspace `DEFAULT` chart.
3. Store new ledger amounts as integer currency minor units; API and JSON inputs use decimal strings.
4. Create separate `ledger_entries`, `ledger_lines`, and dimension-link tables for balanced local control entries.
5. Permit only `Draft -> Validated -> Voided`; do not implement a `Posted` state or source-ERP writeback.
6. Enforce balance, review metadata, and post-validation immutability with both atomic service transactions and SQLite triggers.
7. Enforce creator/validator separation when both actors are known local users.
8. Require organization, entity, period, journal, chart, currency, account, and dimension relationships to resolve locally.
9. Publish bounded path-free snapshot and trial-balance contracts, with authenticated API and first-class CLI surfaces.
10. Include the new tables in local backup/restore and sanitized DB export coverage.

## Consequences

- Existing journal-control imports remain backward compatible.
- Validated local entries are reliable control artifacts but are not source-system postings or statutory books.
- Integer minor-unit storage avoids binary float drift for one registered currency per entry.
- Cross-currency conversion, numbering sequences, PostgreSQL behavior, financial statements, and subledgers require later explicit designs.
- The legacy workspace-wide account-code uniqueness remains until a separately tested compatibility migration can safely relax it.
