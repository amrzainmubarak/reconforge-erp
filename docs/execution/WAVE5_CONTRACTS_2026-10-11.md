# Wave5 source and integration contracts

Start: accepted Draft PR130 at `6362724f2337a79c3d7569574f7bf9591a018524`, above PR129 through PR124. Local and remote main remain `b61ea56bb9c135fda12546e173795af3c243e4fb`. Primary checkout remains on `69951414` with its two original uncommitted schema edits protected by SHA256.

Baseline: live authenticated PR130, main-ref and original successful CI run38081451376 responses retained separately under output/wave5-baseline-6362724f. Individual bounded API refresh attempts timed out; successfully retrieved responses were individually inspected. Exact-source hosted 38-job acceptance is reused as the full baseline, not presented as a new regression run. Fresh Python3.12.13 Ruff passed; eight relevant pure/domain suites passed61 cases with zero skips in26.53s. One inherited Starlette/httpx deprecation warning remains. Agent operations also passed21 sourcing-adjacent cases in1.94s. This is no performance result.

## Ownership

| Owner | Independent worktree | Owned slice | Shared dependencies |
|---|---|---|---|
| Manufacturing | reconforge-manufacturing-wave5 | New manufacturing_execution domain/application/adapter/schema/module/UI/tests/oracle | Migration133, native movement relevance marker, shared reservation/FIFO protection and exact private posting admission |
| Corporate finance | reconforge-finance-wave5 | New intercompany_operations source/paired plans/settlement/group elimination/report/UI/tests/oracle | Migration134, all-entity current authority, exact private native posting admission and protected source dispatch |
| Operations | reconforge-operations-wave5 | New procurement_sourcing PR/RFQ/quotes/reviewed award into existing BPC1; source-linked manufacturing requirements | Migration135, budget and original-source return/capacity contracts when proven |
| Root | reconforge-integration-wave5 | Shared architecture, permissions, API/nav, native source hooks, Alembic, CI/restore/package integration, profiling and benchmark evidence | All owner artifacts; reviews rotate manufacturing→finance→operations→manufacturing |

No owner edits the primary checkout or another worktree. All new authors and committers are Amr. Shared-file changes require coordination; no full regressions after small edits.

## Financial contracts

ME1 uses original FIFO components and native issue movements, then native WIP journals and existing IRP1 finished-goods receipts. Issued cost equals remaining WIP plus finished-goods cost plus scrap expense. BOM revisions and original base-unit quantity precision are retained; cross-UOM BOM conversion remains excluded. Partial cumulative allocations conserve the final residual. Manufacturing reservations share stock lock keys with sales; native relevance guards must exit before protected-table access for unrelated ordinary roles. No independent inventory/GL engine or MRP completion assertion.

IC1 uses two explicitly authorized trading entities and an explicit existing group-adjustment scope, all on an identical retained functional/reporting currency policy. Recognition and settlement post both parties atomically in Finance Core. Reviewed elimination journals post to the explicit group-adjustment scope, preserving original trading books. Consolidated management reports reuse reviewed mappings and native effect drill-down from all three scopes. No automatic FX/tax/legal-company/statutory inference. A request bound to one entity never clears its established scope to reach another.

Sourcing preserves approved requisitions, frozen supplier quotes, deterministic selection and three-person award into existing BPC1 multiline PO/budget/AP. Source-linked manufacturing requirements validate canonical scope, item/UOM/quantity precision, retained digest and current authority. Demand provenance alone is not MRP. Supplier-return budget reinstatement needs an original-owned reversed-consumption event and net receiving capacity closure; the accepted exclusion remains until this complete contract is implemented and verified.

All slices preserve exact arithmetic, double entry, ACID, FORCE RLS, current grants after locks, immutable source/audit/outbox, versioned idempotency and public source-inverse refusal. Direct SQL, concurrent conflicting commands, permission withdrawal, lost responses, failure rollback and populated restore are mandatory acceptance gates.

## Measurement admission

The root's first opt-in CPU/SQL/memory discovery run is on immutable accepted636. It is profiling evidence, not a quiet speed comparison. Final baseline/candidate measurements use equal workloads, fresh populations, at least three alternating trials where resources permit, warmup, raw power/frequency/resources and independent financial oracles. New mixed API/manufacturing/intercompany runs retain their own scope. Runtime changes after measurement require final-head retest. No old Wave4 percentage becomes a Wave5 result. 100K/1M and monetary cost remain unproven until actually admitted and measured.
