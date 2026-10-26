# ADR0872 — Stable leave identity, entity RLS and unsupported native source containment

Date: 2026-10-26. Status: implemented bounded repairs; release BLOCKED.

## Decision

Leave requester/reviewer authority uses stable canonical user IDs. Display labels
remain labels. Renaming or reusing a username cannot transfer ownership or permit
self-review. A canonical employee without a linked login can receive HR-managed
entitlement in its own selected scope, but cannot authorize a personal request or
review from an inferred historical label.

PostgreSQL revision0156 binds both leave tables to the canonical employee tenant,
workspace, organization and legal entity through USING and WITH CHECK policies.
Existing rows are preserved; unbound legacy records are not guessed into an entity.
Populated downgrade refuses rather than restoring a broader disclosure policy.
Recovery uses retained backups and a forward repair; an empty database can roundtrip.
No application schema-owner privilege or automatic operational grant is added.

The inherited multi-register acquisition adapter emitted extra fields under the
exact single-register source schema and could not replay or post lawfully. It now
fails before transaction/I/O with asset_multi_register_owner_required. Supported
single-register acquisition/depreciation/disposal remains unchanged and is tested
natively. No shadow ledger or relaxation of the exact native source guard is allowed.
Multi-register operation remains unavailable pending its own versioned native owner,
migration, per-register invariants, restore/replay and financial approval evidence.

SQLite quality repository construction uses savepoints and individual statements;
it cannot commit a caller's unrelated writes. Quality records do not establish
actual stock quarantine or a financial effect. The existing integration test stays
red where that missing effect is expected; the manufacturing cycle remains BLOCKED.

## Compatibility and rollback

Existing leave response display labels remain, with stable approved_by_user_id
also returned. Historical label-only ownership is not automatically upgraded.
The unsupported multi-register method has no API caller identified; its explicit
refusal replaces generation of an unverifiable native draft. Callers must retain
and remediate any earlier invalid drafts; no destructive cleanup is performed.

Do not roll back156 over populated leave tables. Use a forward correction or an
independently verified isolated restore, preserving original evidence. The previous
broad-scope policy and unsupported source behavior are not safe production fallbacks.

## Evidence

Original four local HCM failures and native cross-entity leak are preserved under
output/assurance-20261026/program-entry-auth and qa-program-hcm-complete.
Successor local65 and independent native15 cases retain command/source receipts.
Native stock/asset safety2 cases independently verify18 unchanged tables for
unsupported requests and the supported single-register lifecycle. See current
ENTERPRISE_PROGRAM_2026-10-26 and ENTERPRISE_CYCLES_2026-10-26 reports.
