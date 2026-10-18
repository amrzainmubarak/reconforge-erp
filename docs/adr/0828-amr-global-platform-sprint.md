# Amr global financial and operations foundation sprint

Status: accepted for implementation; capability acceptance requires measured gates.
Date: 2026-10-03

The user authorized expansion toward a Global Financial & Operations Platform and
stopped the reviewed Inventory receipt lane. Commit `25a7adab` preserves that
lane's implementation and existing draft reports; it does not certify API/UI,
live migration/restore, or full trade-cycle acceptance. Main remains `b61ea56b`.

Inspection found governed organizations/workspaces, local and server identities,
RBAC/ABAC, maker-checker, evidence, AR/AP, Inventory, GL, consolidation, durable
jobs, outbox, notifications transports and operational controls. Recreating these
would add inconsistent authorities. Keep the modular monolith and its current
domain/application/adapter separation; evolve existing contracts additively.

Three bounded vertical slices run in independent worktrees, with exclusive files:

1. User notification inbox: immutable publication, recipient and hierarchy scope,
   exact replay/conflict, append-only acknowledgement, safe translated topic keys,
   SQLite/PostgreSQL, authorized API and authenticated Arabic/English client.
2. Operational budget control: retained currency policy and canonical scope,
   independently approved envelopes, conserved reserve/release/consume events,
   atomic oversubscription refusal, SQLite/PostgreSQL, API and real client.
3. Outbox fencing and terminal recovery: monotonic claim generations, stale and
   expired worker refusal, bounded recovery at the attempt ceiling, immutable
   delivery evidence, live races and a reproducible synthetic recovery workload.

The lead owns router/factory/permission registration, SQLite migrations and backup,
shared web navigation, Alembic dependency integration, execution state and final
acceptance. Agents own capability-private implementations/tests/manifests and
ADRs0825-0827. Reserved migrations are SQLite51-53 and PostgreSQL0101-0103, after
the paused lane's SQLite50/PostgreSQL0100. No parallel editor modifies a shared
registration file. Worktree changes are reviewed and cherry-picked sequentially.

Dependency order: inspect and retain current baseline; implement private slices in
parallel; integrate inbox51/0101, budget52/0102, fencing53/0103; verify fresh and
populated upgrades, backup/restore, authorization, concurrency and recovery;
run whole Python and web regressions on a fresh locked supported runtime. Failed
or prerequisite-skipped commands remain explicit and do not count as acceptance.

Budget consumption records operational utilization, not a GL posting, payment or
tax calculation. Inbox resource identifiers are references, not proof of access to
the referenced financial object. Outbox transport remains at-least-once; fencing
controls database acknowledgement and does not guarantee one external send.

No new dependency or license change is selected. Expansion is an architectural
target, not a completed ERP, statutory reporting, bank readiness or compliance
claim. Community stays local, network delivery remains opt-in, and financial
approval remains a human action. Rollback retains a pre-upgrade verified backup;
populated downgrades must refuse evidence loss. No source/evidence row is removed
to make a downgrade pass, and no production deployment or main merge is included.
