# ADR 0271 — Explicit consolidation translation evidence projection

- **Status:** Accepted
- **Date:** 2026-08-03
- **Scope:** SQLite and PostgreSQL consolidation-close read boundaries

## Decision

Expose a deterministic `translation_evidence` projection on every
replay-verified close run. The projection is derived only from the verified
`ConsolidationTranslationResult` already embedded in the worksheet; it does
not recalculate FX, post a journal, or perform provider I/O.

The projection binds the translation result digest and adds a digest over the
canonical line-level FX lineage, line count, source currencies, rate IDs and
rate types, reporting currency, pre/post balances, the explicit translation
adjustment, and exact unrounded/rounded deltas. SQLite and PostgreSQL use the
same application helper, so the public read contract cannot drift by backend.

## Rationale

Persisted close evidence must make currency conversion and rounding reviewable
without requiring consumers to understand the full worksheet JSON. Reusing the
already replay-verified result avoids a second calculation path and preserves
determinism and backward compatibility.

## Compatibility and limits

This is an additive read projection; no database migration is required. Existing
pre-0057 PostgreSQL compatibility rows still use their existing replay rules.
The evidence is synthetic control-journal/worksheet evidence only: it is not
statutory consolidation, a live-rate feed, ERP/bank interoperability, or
source-system write-back.

