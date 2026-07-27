# Target-State Architecture

The target is a modular monolith first, with independently testable bounded contexts.
Microservices are deferred until an operational need is demonstrated.

## Bounded contexts

```text
Identity & Access       Organization & Master Data
Finance & Close         Payables / Receivables / Treasury
Procurement / Sales     Inventory / Warehouse
Manufacturing / Assets  Projects / Budgets / Tax
Reconciliation          Controls / Risk / Exceptions
Workflow & Notifications Audit & Evidence
Reporting               Integrations
```

Each context owns domain models, application services, repository interfaces,
permissions, migrations, audit events, and tests. API routes translate contracts and
delegate to application services; they do not contain accounting rules.

## Deployment modes

1. Local edition: SQLite, local files, and synchronous CLI/Studio workflows.
2. Isolated server foundation: database-per-tenant SQLite routing is available for bounded self-hosted deployments; each request requires an explicit validated tenant header.
3. Server edition: PostgreSQL, Redis, and S3-compatible object-storage boundary foundations now exist; full domain persistence, worker processes, and end-to-end tenant context integration remain required.
4. Hosted edition: shared database with RLS or database-per-tenant, centralized identity, object isolation, and operational observability.

The server and hosted modes are design targets until contract tests and deployment
artifacts prove them.

## Financial correctness rules

- Money is represented by a strict Decimal/minor-unit type with currency and rounding policy.
- Invalid values are errors/data-quality records, never implicit zeroes.
- Reconciliation output accounts for every source-side row exactly once according to its configured cardinality.
- Matching uses candidate generation, policy constraints, deterministic scoring, global assignment, and stable tie-breaking.
- Posted financial records are immutable; corrections use reversals or correction documents.
- Business mutation, audit event, and outbox event commit atomically.

## Persistence and events

Repositories isolate SQL and enforce tenant scope. PostgreSQL schema changes use the
Alembic migration chain with expand-and-contract, backup, restore, and rollback/
roll-forward tests; SQLite local schemas retain the existing versioned migration path.
Domain events
are written to a transactional outbox and delivered by workers with retry, idempotency,
dead-letter, and replay semantics. The local foundation already provides the durable
claim/lease state machine and a bounded worker runtime; external transport, queue
orchestration, tenant context, and worker deployment remain deployment concerns.

## Security architecture

Backend authorization combines RBAC, data scope, amount/state policies, and segregation
of duties. Enterprise identity adapters (OIDC/SAML/SCIM/MFA) remain optional modules,
never UI-only checks. Secrets belong in deployment secret stores. Audit and evidence
exports include canonical hashes and verification metadata.

## Decision gates

No hosted/enterprise readiness claim is allowed until tenant isolation, PostgreSQL,
centralized sessions/rate limiting, object storage, worker recovery, backup restore,
security testing, and end-to-end financial-cycle tests are demonstrated.
