# Consolidation ownership, NCI, and elimination worksheet v1

This experimental Finance Core contract turns one verified translation-result
v1 artifact into a deterministic, balanced, non-posting group worksheet. It is
a programmatic library/application boundary; the separate local SQLite
lifecycle in `docs/consolidation-close-lifecycle.md` can persist and approve a
verified worksheet, but the worksheet contract itself still has no posting
effect.

## Required inputs

- One replay-valid `ConsolidationTranslationResult` from ADR 0210.
- Exact period start/end and reporting dates.
- A versioned policy naming the group parent and two distinct NCI presentation
  accounts.
- Effective-dated ownership records with exact Decimal percentage, source
  digest, version, preparer, different approver, and approval timestamp.
- Zero or more explicit elimination proposals. Each proposal contains at least
  two group entities, non-zero reporting-currency Money lines, source references
  and digests, a rationale, and exact zero balance.
- A worksheet preparer and timezone-aware whole-second preparation timestamp.

## Fail-closed rules

- The reporting date must be inside the declared period.
- Ownership history for one subsidiary cannot overlap.
- Ownership approval and elimination preparation timestamps cannot follow the
  worksheet preparation timestamp.
- Every translated non-root entity has exactly one active parent on the
  reporting date. The parent has none; the active graph is rooted and acyclic.
- Full-consolidation v1 rejects a direct active interest at or below 50%.
- Ownership uses finite Decimal only. Binary float, invalid dates, actor reuse,
  unknown entities, duplicate IDs, and invalid source digests are rejected.
- Elimination lines must use the translation reporting currency and a consistent
  account type. Each proposal balances to zero and line IDs are unique across
  the worksheet.
- The verified translation accounts plus unposted CTA balance before
  eliminations; the final worksheet also balances exactly.

## Output and explanation

The closed `consolidation-worksheet-v1` artifact retains:

- the complete translation request/result and digest;
- all declared ownership history plus the selected active interest IDs;
- root-to-entity ownership paths, direct/effective group percentages, and NCI
  percentages;
- translated net assets and period profit per subsidiary;
- rounded and unrounded NCI net-assets/profit presentation with rounding deltas;
- every elimination line, amount, source reference/digest, rationale, and zero
  balance;
- base and post-elimination group accounts with contributing references;
- zero pre/post balances, policy digest, request/result digests, and a stable
  worksheet ID; and
- `posting_effect=none`, `posted=false` for NCI and eliminations.

`verify_consolidation_worksheet_payload` reconstructs the translation and
worksheet from the embedded closed request, then compares canonical output. An
attacker cannot change a financial output and merely recompute the outer hash.

## Exact limits

NCI v1 is a presentation allocation over translated signed account classes. It
does not implement acquisition-date fair values, goodwill/bargain purchase,
pre/post-acquisition reserves, ownership changes, equity-method or joint
arrangement accounting, historical FX recycling, tax, statutory disclosures,
or accounting-standard conclusions.

The worksheet slice itself does not persist ownership or mutate a source
ledger. Migration 25 adds a separate local SQLite control-journal lifecycle for
verified worksheets, maker-checker approval, exact local posting/reversal
effects, and period lock/reopen evidence. PostgreSQL parity, statutory
statements, acquisition accounting, live rates, API/CLI/UI exposure, ERP/bank
provider calls, and write-back remain later `P4-FIN-002` gates.

## Verification

```bash
python -m pytest tests/test_consolidation_translation.py tests/test_consolidation_lifecycle.py -q
python -m ruff check reconforge/domain/consolidation_lifecycle.py tests/test_consolidation_lifecycle.py
python -m mypy reconforge
```

See ADR 0211 for the decision and rollback boundary.
