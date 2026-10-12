# ADR0854: Native production, group journals and sourcing ownership

Date: 2026-10-11. Status: accepted implementation architecture; final runtime
acceptance remains an independent gate. Base: accepted PR130 `6362724f`.

Extend the modular monolith through three independent source owners. ME1 keeps
versioned reviewed BOMs and current stock reservations, freezes exact original
FIFO issue costs into WIP, and owns native IRP finished-goods receipts plus
abnormal-scrap expense. IC1 atomically owns the two original company effects and
cash settlement effects, and posts eliminations to an explicitly authorized
group-adjustment scope. Sourcing owns retained requisitions and quotation
selection, then atomically awards an existing budget-bound BPC1 purchase order.

All effects use existing GL, inventory, policy, identity, audit and outbox engines.
Private participants bind to the exact live owner, connection, tenant and native
entry/receipt identity. Public native posting and receipt lifecycles cannot
advance detached owned sources. SQL deferred closure covers reverse edits and
direct SQL writes. Ordinary namespaces must return before protected owner-table
queries; this preserves legacy role compatibility and avoids the prior dispatch
ACL defect. New modules use additive migrations133–135; original published
schemas and migrations remain byte-identical.

Permission catalogs seed new tenants without automatically granting existing
roles. New mutations require current human identity and step-up, with independent
preparer/reviewer/poster. Multi-entity operations retain organization/workspace
scope and explicitly recheck all three entities; an entity-bound request never
clears its GUC to escape FORCE RLS.

Material-only abnormal-scrap costing and same-policy intercompany accounting are
bounded foundations. Labor, overhead, routing, rework, net-shortage MRP, foreign
group translation, country statutory tax, and budget-bound supplier restitution
remain separate dependencies until their full financial closure is implemented.

Actual636 CPU/SQL profiling motivates current scoped account batching and
parameterized128-row draft inserts. Every native RLS policy, immediate row
trigger, deferred financial invariant and original replay check still executes.
Candidate4102b039 is not an accepted speed claim. Final runtime source requires
quiet, alternating baseline/candidate repetitions with raw resource evidence and
independent financial oracles. Neither authentication strength nor financial
controls are reduced to improve a benchmark.

Rollback rejects populated owner histories and retained permission grants;
operators restore a verified pre-upgrade backup. No production migration,
default-branch update, PR merge or new dependency is authorized by this ADR.
