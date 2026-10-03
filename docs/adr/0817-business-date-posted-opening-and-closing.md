# 0817: Verified business-date opening, activity and closing

Status: accepted for bounded recorded-posting business-date balances, 2026-10-03.

## Decision

Add an independent finance-posted-balances-v1 contract over immutable reviewed
operational posting effects. Opening includes all retained effect activity before
the selected fiscal period starts. Activity includes its start through the
inclusive canonical as-of date; closing equals opening plus activity. Report
gross turnover and net account balances separately, with effect/entry/period/
date/line drill-down and an exact deterministic report digest.

Resolve canonical workspace, organization, entity and period before reading
history. Preserve current PostgreSQL RLS and transaction-local scope. Independently
verify every effect snapshot, policy and source audit/outbox affinity. Reject
incompatible retained currency policies and contributions assigned to overlapping
alternate periods. Closed periods remain readable; draft/control-only entries,
future business dates and sibling scopes are excluded. No missing opening balance
or legacy validated entry is silently adopted.

Bound the report to1000 effects,10000 contributing lines and2MiB combined verified
snapshot bytes. Load effects incrementally and stop at the first exceeded budget;
the final canonical report is also bounded to2MiB. Validate closed structure,
canonical scope identifiers, typed currency policy, arithmetic, contributing
effect affinity and digest before projection. Malformed evidence produces the
shared typed error. API monetary integers become exact strings; report_json
retains the original canonical integer representation for digest verification.

The report is a business-date view of currently recorded immutable history.
A later recorded backdated posting can change a later report for that date.
This does not claim historical knowledge-time reproducibility, automatic opening
imports, statutory fiscal close, complete GL, or integrated trade posting.
The existing selected-period trial-balance response remains unchanged.

## Evidence and rollback

POSTED_BALANCES_2026-10-03.json binds clean immutable866d943a,127 local passes
and4 actual PostgreSQL/HTTP passes, all without skips. Global Ruff/Mypy/Bandit,
build and diff checks pass on the same source; native16.14 restore takes35.505s
including its wrapper and verifies owned source/restored database removal.
Golden SQLite/PG
results include opening10000, reversal to0, then closing2500 across July/August;
an unposted entry and future September entry do not contribute. Actual HTTP
preserves9007199254740993 exactly. SQLite caller ownership/backup restore and
native PostgreSQL restored as-of digests are required separately.

Independent review reproduced malformed policy acceptance and eager30000-line
loading before a10000-line rejection. Those original probes remain retained;
the fixes require fresh final proofs. A concurrent prerequisite-store edit also
caused two passing tests to fail source-stability acceptance, retained separately.

Rollback removes the additive read API/CLI without modifying financial records.
Keep historical report contracts and digests verifiable. No storage migration
is required; previous posting/effect readers remain compatible.
