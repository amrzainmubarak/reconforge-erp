# Field-level access

`CentralPolicyEngine` supports an explicit requested-field versus authorized-field contract. The contract denies by default when a requested field is outside the authorized set. `project_fields` then produces an allowlisted projection, replacing explicitly masked fields with `[REDACTED]` and retaining deterministic masked/denied evidence.

This does not claim that all existing routes or UI components have migrated. Integrators must supply field sets from a versioned policy and test each sensitive surface.

## E-1044 migrated surface

The local-only Individual Cashflow run response uses central recursive
allowlists for the run envelope, decisions, canonical Money values, input
digests, and known status counts. Unknown future result fields are dropped and
malformed nested collections fail closed before serialization. This is a
bounded disclosure control for the reviewed response family, not universal
field-level authorization, bank authenticity, or production readiness. ADR
0704 records the decision and rollback.

## E-1043 migrated surface

Inventory Planning count-session lifecycle, count-session lists, reorder-rule
mutation/list, reorder signals, and snapshots now use central recursive
allowlists across local SQLite and PostgreSQL. Count lines, session summaries,
reorder rules, source metadata, pagination, signals, and snapshot collections
are projected explicitly; unknown adapter/storage fields are dropped before
serialization. Exact quantities, approval metadata, workspace scope, and
lifecycle behavior remain compatible. This is a bounded disclosure control
for the reviewed response family, not universal field-level authorization,
external IAM, or production readiness. ADR 0703 records the decision and
rollback.

## E-1042 migrated surface

Finance Core chart, account, dimension, dimension-value, and journal list and
mutation responses now use central allowlists across local SQLite,
tenant-scoped PostgreSQL, and the bounded legacy ledger adapter. The deliberate
local/server/legacy field union is retained, including the server workspace
marker; unknown adapter/storage fields are dropped before serialization. This
is a bounded disclosure control for the reviewed master-data response family,
not universal field-level authorization, external IAM, or production
readiness. ADR 0702 records the decision and rollback.

## E-1041 migrated surface

Bank Statement Control create, list, and read responses now use central
top-level and recursive allowlists across local SQLite and PostgreSQL. The run
envelope, report, amount tolerance, canonical money values, status counts, and
bank-to-ledger decisions are projected explicitly; unknown adapter/storage
fields are dropped before serialization and malformed nested mappings fail
closed. Evidence digests, workspace scope, and no-network/no-posting behavior
remain compatible. This is a bounded disclosure control for the reviewed
response family, not bank-source authenticity, payment initiation, universal
field-level authorization, external IAM, or production readiness. ADR 0701
records the decision and rollback.

## E-1040 migrated surface

Manufacturing Cost Control create, list, and read responses now use central
top-level and recursive allowlists across local SQLite and PostgreSQL. The run
envelope, report, amount tolerance, maximum scrap quantity, canonical money
and quantity values, status counts, and production decisions are projected
explicitly; unknown adapter/storage fields are dropped before serialization
and malformed nested mappings fail closed. Evidence digests, workspace scope,
and no-network/no-posting behavior remain compatible. This is a bounded
disclosure control for the reviewed response family, not universal field-level
authorization, external IAM, or production readiness. ADR 0700 records the
decision and rollback.

## E-1039 migrated surface

Retail Settlement create, list, and read responses now use central top-level and
recursive allowlists across local SQLite and PostgreSQL. The run envelope,
report, tolerance, canonical money values, status counts, settlement decisions,
and optional variance values are projected explicitly; unknown adapter/storage
fields are dropped before serialization. Evidence digests, workspace scope,
and no-network/no-posting behavior remain compatible. This is a bounded
disclosure control for the reviewed response family, not universal field-level
authorization, external IAM, or production readiness. ADR 0699 records the
decision and rollback.

## E-1038 migrated surface

Professional invoice/payment create, list, and read responses now use central
top-level and recursive allowlists across local SQLite and PostgreSQL. The run
envelope, report, canonical money values, status counts, decisions, amount
tolerance, and amount variance are projected explicitly; unknown adapter or
storage fields are dropped before serialization. The existing evidence digest,
workspace scope, and no-network/no-posting behavior remain compatible. This is
a bounded disclosure control for the reviewed response family, not universal
field-level authorization, external IAM, or production readiness. ADR 0698
records the decision and rollback.

## E-1037 migrated surface

Receivables customer, invoice, receipt, credit-exposure, and aging responses
now use central top-level and recursive nested allowlists across local SQLite
and PostgreSQL. Invoice lines, receipt allocations, and aging items are
projected explicitly; malformed nested collections fail closed. Unknown future
adapter/storage fields are dropped before serialization while the existing
response envelopes, exact minor units, lifecycle behavior, and scope checks
remain compatible. This is a bounded disclosure control for the reviewed
Receivables response family, not universal field-level authorization, external
IAM, or production readiness. ADR 0697 records the decision and rollback.

## E-1036 migrated surface

Payables supplier-invoice create, list, submit, match, and approve responses
now use central invoice, nested-line, and three-way-match allowlists across
local SQLite and PostgreSQL. Unknown future adapter/storage fields are dropped
before serialization while exact quantities, minor units, and the existing
lifecycle responses remain compatible. This is a bounded disclosure control
for the supplier-invoice response family, not complete Payables response
coverage, universal field-level authorization, or production IAM. ADR 0696
records the decision and rollback.

## E-1035 migrated surface

Payables goods-receipt posting responses now use central top-level and
nested-line allowlists across local SQLite and PostgreSQL. Unknown future
adapter/storage fields are dropped before serialization while exact quantity
fields and the existing direct lifecycle response remain compatible. This is a
bounded disclosure control for the goods-receipt response family, not complete
Payables response coverage, universal field-level authorization, or production
IAM. ADR 0695 records the decision and rollback.

## E-1034 migrated surface

Payables purchase-order create, submit, and approve responses now use central
top-level and nested-line allowlists across local SQLite and PostgreSQL.
Unknown future adapter/storage fields are dropped before serialization while
exact quantity/price fields and the existing direct lifecycle response remain
compatible. This is a bounded disclosure control for the purchase-order
response family, not complete Payables response coverage, universal
field-level authorization, or production IAM. ADR 0694 records the decision
and rollback.

## E-1033 migrated surface

Payables supplier save and list responses now use a central supplier allowlist
across local SQLite and PostgreSQL. Unknown future adapter/storage fields are
dropped before serialization while the existing direct response shape and
pagination metadata remain compatible. This is a bounded disclosure control
for the supplier-master response family, not complete Payables response
coverage, universal field-level authorization, or production IAM. ADR 0693
records the decision and rollback.

## E-1032 migrated surface

Inventory Core movement list/create/read/post/void, on-hand, control-exception,
summary, and snapshot responses now use central allowlists across local SQLite
and PostgreSQL. Movement lines, on-hand balances, control exceptions, and
snapshot source/summary/collections are projected recursively; malformed
nested data fails closed. The snapshot reuses the E-1031 master-resource
projectors. Exact quantity fields and existing response envelopes are retained
for compatibility. This is a bounded disclosure control for the reviewed
operational response family, not universal field-level authorization or
production IAM. ADR 0692 records the decision and rollback.

## E-1031 migrated surface

Inventory Core unit-of-measure, item, warehouse, location, and lot/serial
list/mutation responses now use explicit central resource allowlists across
local SQLite and PostgreSQL. This is a bounded disclosure control for the
reviewed master-resource family, not complete Inventory Core response
coverage, universal field-level authorization, or production IAM. ADR 0691
records the decision and rollback.

## E-1030 migrated surface

Inventory Valuation Reversal summary, snapshot, list, create, read, approve,
and cancel responses now use central top-level and effect allowlists across
local SQLite and PostgreSQL. The snapshot recursively projects source,
summary, and reversal records; malformed nested data fails closed. This is a
bounded disclosure control for the reviewed reversal response family, not
universal field-level authorization or production IAM. ADR 0690 records the
decision and rollback.

## E-1029 migrated surface

Inventory Valuation policy list/save, cost-layer list, summary, and snapshot
responses now use central allowlists across local SQLite and PostgreSQL. The
snapshot is recursively projected across source, summary, policy, document,
and open-layer collections; malformed nested collections or records fail
closed. This is a bounded disclosure control for the reviewed response
family, not universal field-level authorization or production IAM. ADR 0689
records the decision and rollback.

## E-1028 migrated surface

Inventory Valuation document list, create, read, approve, and cancel responses
now use a central top-level allowlist across local SQLite and PostgreSQL. The
input-cost, valuation-line, and layer-consumption collections use independent
child allowlists, so future adapter/storage fields do not silently become
financial API output. This is a bounded disclosure control for the reviewed
document response family; valuation policies, cost layers, and snapshots are
separate surfaces. It is not universal field-level authorization or
production IAM. ADR 0688 records the decision and rollback.

## E-1027 migrated surface

Master Data currency, organization, legal-entity, branch, and fiscal-period
list/mutation responses now use explicit resource allowlists across local
SQLite and PostgreSQL. The versioned master-data snapshot also projects its
top-level, summary, source, resource collections, and currency-registry nested
records; malformed nested records fail closed. This is a bounded disclosure
control for the reviewed Master Data response family, not universal
field-level authorization or production IAM. ADR 0687 records the decision
and rollback.

## E-1026 migrated surface

Finance Core ledger-entry list, read, create, validate, and void responses now
use one central allowlist across local SQLite, PostgreSQL Finance Core, and the
bounded legacy PostgreSQL ledger shape. Nested ledger lines are projected with
their own allowlist, preserving reviewed financial and lineage fields while
dropping unknown adapter/storage fields. This is a bounded disclosure control
for the ledger-entry response family, not universal field-level authorization
or production IAM. ADR 0686 records the decision and rollback.

## E-1017 migrated surface

The local and Server Profile `GET /api/v1/evidence/records/{evidence_id}/drill-down`
surface now consumes a single evidence response allowlist.  Ordinary reads
receive the non-sensitive projection; `include_sensitive=true` still requires
`evidence.manage`, requests the reviewed complete field set through the Server
Profile central policy boundary, and remains subject to the allowlist.  Nested
evidence links are projected independently.  Unknown future fields are
dropped, and each evidence node returns projection version, mode, masked and
denied fields, and a deterministic digest.  The existing `***redacted***`
token is retained at this API boundary for compatibility.

This is one migrated surface, not universal field-level authorization or
production IAM effectiveness.  The complete decision and rollback boundary
are recorded in ADR 0677.

E-1018 extends the same boundary to the evidence list, single-record get, and
Server Profile registration response. List/get use the safe projection;
registration uses the reviewed sensitive allowlist after `evidence.manage`
authorization. The projection metadata remains additive and unknown adapter
fields are dropped. ADR 0678 records this extension and its limits.

## E-1019 migrated surface

The legacy `GET /api/v1/audit/events` response now uses one central allowlist
for both the local SQLite and PostgreSQL adapter shapes. Actor and tenant
identity, object/resource identifiers, request IDs, reasons, and decoded
metadata are masked with `[REDACTED]`; unknown adapter fields are dropped.
The route retains its existing `audit.read` requirement and Server Profile
tenant-policy re-check. This is a disclosure boundary for one legacy response
family, not universal field-level authorization or production IAM. ADR 0679
records the decision and rollback.

## E-1020 migrated surface

Server Profile evidence requirement and checksum verification mutation
responses now consume closed allowlists. Known fields needed by the existing
authorized operation remain available, deterministic `field_access` metadata
is additive, and unknown adapter fields are dropped. This covers two mutation
response contracts and does not establish universal field-level authorization
or production IAM. ADR 0680 records the decision and rollback.

## E-1021 migrated surface

The `/api/v1/close` period, task, and readiness responses now use central
allowlists for the union of the local SQLite and PostgreSQL shapes. This
prevents SQLite `SELECT *` schema growth or a future adapter field from
silently expanding the response. Existing fields and route permissions are
preserved. This is a bounded disclosure control, not universal field-level
authorization or production IAM. ADR 0681 records the decision and rollback.

## E-1022 migrated surface

The local `/api/v1/exceptions` list, assignment, and status responses now use a
central exception-record allowlist. This prevents `SELECT *` schema growth or
future storage fields from silently expanding the API while preserving the
existing response envelope and RBAC boundary. The route remains explicitly
local-only. This is a bounded disclosure control, not universal field-level
authorization or production IAM. ADR 0682 records the decision and rollback.

## E-1023 migrated surface

Consolidation-close period and run responses now use central allowlists for the
reviewed local SQLite and PostgreSQL shapes. Journal lines, effect records, and
effect lines are projected independently; reviewed PostgreSQL evidence arrays
remain available while internal worksheet payload/cache fields and unknown
future adapter/storage fields are excluded. This is a bounded disclosure
control for the consolidation-close response family, not universal
field-level authorization or production IAM. ADR 0683 records the decision
and rollback.

## E-1024 migrated surface

Account reconciliation list, read, create, and lifecycle responses now use a
central allowlist across the local SQLite and PostgreSQL shapes. Nested
reconciliation items are projected independently, while known financial,
workflow, and audit-attribution fields remain available. Unknown future
storage/adapter fields are dropped before serialization. This is a bounded
disclosure control for the account-reconciliation response family, not
universal field-level authorization or production IAM. ADR 0684 records the
decision and rollback.

## E-1025 migrated surface

PostgreSQL reconciliation run, canonical-input, deterministic-result, and
exception responses now use central allowlists. Nested run collections and
paginated child responses are projected by their own reviewed contracts, while
known financial and execution fields remain available. Unknown future adapter
fields are dropped before serialization. This is a bounded disclosure control
for the reconciliation response family, not universal field-level
authorization or production IAM. ADR 0685 records the decision and rollback.
