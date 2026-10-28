# ADR 0880: Integrated ERP vision and evidence gates

Status: proposed; public positioning unchanged.  Date: 2026-10-28.

## Context

The user has requested a long-term, locally deployable open-source ERP vision,
with reconciliation, financial integrity and evidence as core strengths. The
existing positioning describes a local reconciliation and control platform
alongside source systems. A vision is not evidence that an integrated ERP is
available. At source `b1ae1b5e7aad0cc9893bfda65ff44b422aaa279b`, financial
replay, quality entity isolation, five complete cycles and release gates remain
open; see `docs/execution/STATE.md` and the dated baseline refresh.

## Proposed direction

Grow the current modular monolith incrementally towards integrated finance,
operations, sales, procurement, manufacturing, people and projects. Introduce
each capability through an actual use case with explicit data ownership,
versioned contracts, authorization, financial invariants, traceability, tests
and operational evidence. Preserve offline local use, and add separately
qualified team and customer-operated deployment options. No network or AI
provider is mandatory by default. AI suggestions require human governance.

Protect existing API, CLI, data and replay semantics using versioned policies,
compatibility readers and tested migrations. Never silently assign historical
quality records to an entity. Dependency order is safety and recovery first,
then shared financial/identity foundations, then connected business cycles,
then sector depth and operational scale. A full cycle requires source-to-report
evidence across real interfaces and supported storage, including denial and
failure paths. It cannot be inferred from individually passing components.

## Alternatives and consequences

Maintaining only the existing reconciliation scope would minimize scope but
would not implement the requested vision. A broad immediate rewrite or early
microservices would increase migration and operational risk before financial
and authorization guarantees are proven. Incremental bounded contexts retain
compatibility but take sustained implementation and independent qualification.

This proposal neither changes the MIT license nor approves a release, public
positioning change, compliance claim, pricing or market decision. Public
wording remains governed by the existing positioning until an ADR is approved
and actual claims are supported. Commercial or legal decisions requiring human
authority remain separate. Competitive superiority is an unverified goal.

## Acceptance and rollback

Before approval, review the scope, public positioning, compatibility and
resource implications. Each implemented slice retains its own rollback and
evidence; withdrawing this proposal does not rewrite source records or change
runtime behavior. Source-frozen CI, real PostgreSQL, upgrade/restore and cycle
gates remain separate from this architectural proposal.
