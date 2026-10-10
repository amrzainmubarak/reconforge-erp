# ADR 0845: Governed source abandonment and verified native effect reads

Status: accepted for implementation; integrated acceptance is a separate gate.
Date: 2026-10-10.

## Context

Accepted PR127 is `34b9e7a5b2a7c4d8ae49b641a36de030a878d507`, above
PR126/125/124. Current PR128 head `6995141426fea1670b64313ae1a5b2f1d6064f8f`
contains CA1 collections, LC1 prepaid landed receiving and FA1 assets. Its
hosted gate has real restricted-role dispatch and Bandit failures; it is an
implementation dependency, not a newly accepted baseline. Prepared commercial
and landed-cost claims have no governed release, trapping invoice residual or
receiving capacity. Published posting throughput regresses 23.23% against PR127.

## Decision

Keep all existing ledger, inventory, identity, currency and audit engines. Three
managed worktrees own commercial collections, landed-cost procurement and
finance/evidence respectively. The integration branch retains PR128 ancestry and
does not edit or merge main. All new commits use the configured Amr identity.

Cancellation is a reviewed nonfinancial source decision: retain original source,
draft/validated GL, allocations, historical acknowledgements and append-only
actor/reason/audit/outbox evidence. Only unposted claims can release their
reserved capacity. Current permissions and actor independence apply on every
request including retries. Posted sources require a future explicit financial
inverse; cancellation cannot erase or reverse an existing business effect.

Route ordinary legacy mutations before reading new protected owner tables.
Every relevant native namespace, deleted owner, source/effect mutation and
reserved child still requires closure. Keep invoker security and FORCE RLS;
privilege widening is not a compatibility repair. Additive revisions0124/0125
upgrade existing databases; initial schema and upgrade definitions agree.

Asset proof reads verify existing owner closure and native posting digests,
show exact financial lines, actor separation and evidence references, and
require current scoped read authority. They create no new financial state.

Profile native posting before changing it. Batch snapshot line/dimension reads
only if deterministic content and isolation are unchanged. Retain source-bound
baseline/candidate raw phase timings, workload configuration and independent
money totals. A within-run comparison or exploratory short run cannot establish
a global throughput improvement. Mandatory native gates require executed cases,
zero selected skips and retained JUnit counts, not merely process exit zero.

## Integration and rollback

Owner files and migrations remain separately reviewed. Central integration owns
fresh/upgrade ordering, required CI selection, funded cross-domain oracle,
browser/populated restore, execution state and the Draft PR. Run targeted owner
tests during development and heavy acceptance on one committed source.

Never discard populated source/cancellation/effect history during downgrade.
Use the owner migration guards and an isolated verified pre-upgrade restore
when storage rollback is necessary. Preserve historical failed evidence and the
two pre-existing uncommitted schema edits in the primary checkout. MIT,
dependencies, Community modes and public readiness claims stay evidence-bound.
