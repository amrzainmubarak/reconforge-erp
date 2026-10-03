# ADR 0795: Adopt a pinned AMLSim sample as an offline reconciliation oracle

Date: 2026-10-03. Status: accepted for implementation. Scope: PROD-022.

The user has no company pilot and explicitly requests open-source sources.
Adopt the unmodified 45-record public synthetic AMLSim sample, retaining its
Apache-2.0 license, attribution, exact commit and SHA-256. Do not run its legacy
generator stack. Preserve ReconForge's MIT license and default offline operation.

The sample has no currency or absolute dates. Require explicit scenario currency,
precision and epoch. Accept only the documented single-transfer CSV shape;
reject aggregated rows, duplicate identities, invalid amounts and unknown shape.
Project two sides with independently specified missing/amount/duplicate/date
faults and compare engine decisions to the fault oracle. The oracle must reject
the current scored policy's acceptance of the altered amount/date. Use the new
opt-in strict policy only after its own boundary and compatibility tests pass.

Retain source/rule/decision digests, replay under row permutations and record
runtime and accurately labeled Python allocation memory. This bounded module
tests in-process reconciliation. It provides no PostgreSQL throughput, complete
trade cycle, AML/fraud efficacy, customer hours or independent auditor acceptance
evidence. Later larger inputs and durable-worker execution are separate gates.

Rollback removes this opt-in module and runner; no data migration, external
connection, production write or new runtime dependency is introduced.
