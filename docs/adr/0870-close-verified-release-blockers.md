# ADR0870: Close verified release blockers without replacing financial owners

Date: 2026-10-25. Status: accepted for implementation; release qualification open.

PR143 contains experimental module adapters that were not deployed through the
official migration chains, lacked complete authenticated scope, and exposed
local UI state as business success. Its original CI and scanner failures are
retained in the release evidence. They are not waived.

Register existing enterprise tables in PostgreSQL0153 and SQLite58. Bind HCM
self-service to a real identity: PostgreSQL uses the existing canonical employee;
Community uses an explicit, immutable, manager-provisioned employee/user link.
An unbound historical employee is not automatically claimed by the first reader.
Enterprise adapter initialization failure must fail closed, with no SQLite fallback.

PostgreSQL0154 composes project milestone and profit-in-stock sources over the
existing Finance Core/Finance Posting owner. No second ledger is introduced.
The original source, currency precision/policy, balanced entry snapshot, actor,
command identity and digest remain bound together. Prepare, independent review,
third-person posting and full reversal use the caller's transaction. Generic
posting/reversal cannot bypass the finite source participant. Database guards
seal sources, entries, both endpoints of line/dimension updates, and command
receipts. Existing source hierarchies stay nullable for preservation; a missing
hierarchy cannot be inferred to authorize financial publication.

The transaction scope setter uses the same five parameterized transaction-local
settings for every connection. Remove test-class-name-dependent behavior; no
throughput improvement is claimed. Preserve existing exact scope assertions.

React HCM, CRM and project journeys consume authenticated scoped API results.
HTTP rejection, malformed data and stale session/scope responses cannot produce
success. Amounts retain explicit currency and minor units. Backend unavailable
behavior remains visible; no placeholder business data is substituted.

Migration0151 must retain the intercompany evidence table owned by0063. Its
original workspace/actor foreign keys and records are preserved. New module
registration must not redefine that older contract. Server-scoped artifact
queries must independently bind their selected workspace without widening it.
Its rollback and the new module/bridge rollbacks refuse populated owned tables.
Rollback requires the verified backup/restore path or a reviewed forward repair,
not deletion of records. New source-origin columns are retained on empty0154
rollback because erasing historical origin is not recovery.

Dependencies are upgraded only against matching locked versions and primary
advisories. Default-main alerts, candidate locks, installed developer tools and
actual images are separate evidence scopes. No vulnerability exception or
scanner suppression is added by this decision.

Preserve the exact previously reviewed supply-chain policy in
`supply-chain-policy.retained-8629e9c6.v1.json`, with its unchanged SHA256.
The historical PostgreSQL image validator reads that immutable source; current
locked resolution continues to use the separately validated active policy.
Refreshing active dependencies must neither overwrite historical evidence nor
disable its hash check.

Compatibility: preserve API/CLI names and canonical accounting engines. New
financial command contracts and employee binding are additive. Legacy unbound
self-service now refuses access until explicit provisioning; this is an
intentional security correction requiring operator action. Historical financial
and audit rows are retained unchanged.

Acceptance requires independent security review, native restricted-role tests,
populated recovery, authenticated browser journeys and exact-source CI. This
decision does not close the existing enterprise completion matrix, external
assessment, customer validation, or release gates by declaration.
