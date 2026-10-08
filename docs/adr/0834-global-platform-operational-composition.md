# ADR 0834: Compose existing financial engines into governed operational workflows

Date: 2026-10-08
Status: accepted for implementation; acceptance is tracked separately

The clean source `6c194e7c` already contains canonical organization/workspace
authority, identity administration, RBAC/ABAC, approval engines, immutable
Finance posting, inventory valuation, AP/AR, budget control and durable jobs.
Reimplementing those engines would split authority and financial invariants.

This sprint composes the existing engines into three usable operational
capabilities: live budget management and conserved commitments; independently
reviewed inventory receipts and their atomic inventory/GL effects; and scoped
durable-job inspection, cancellation and recovery controls. The new instruction
authorizes the previously deferred receipt API/Studio integration. Existing
receipt evidence is retained and failing live contracts must be repaired before
acceptance. Unrelated cancellation-projection migration work remains separate.

Platform, Finance/Operations and Enterprise agents own independent branches and
checkouts. The lead owns shared router/permission registration, navigation,
migration/backup inventories and integration. Domain engines remain modular;
all persisted financial effects retain exact units, source digests, current
authority, maker/checker separation and atomic audit/outbox evidence. New
durable-job management permission grants are explicit and least privileged.

Implementation batches end at targeted milestone gates. After integration,
run the whole Python regression, static/security/build checks, live nonowner
PostgreSQL matrix, migration/restore/recovery/concurrency checks, Studio
typecheck/component/build/browser gates and relevant bounded performance
checks. Retain failures and prerequisite skips; do not weaken constraints.

Acceptance describes only executed workflows and their source identities.
Global Financial & Operations Platform is an architectural target; this slice
does not establish complete ERP/banking coverage, production capacity,
availability, compliance or a stable release. Main is unchanged.

Rollback reverts additive UI/API integration and its application changes.
Permission/index migration rollback must preserve retained job history and
refuse unsafe privilege loss. Existing inventory/Finance history is never
removed to roll back a client surface.
