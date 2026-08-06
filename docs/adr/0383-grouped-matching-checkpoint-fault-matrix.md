# ADR 0383: Exercise Every Grouped-Matching Resume Checkpoint

- **Status**: Accepted
- **Date**: 2026-08-06
- **Scope**: Experimental, bounded crash/resume evidence

## Context

The grouped-matching replay profile already injected one fault after the first
committed partition. A single checkpoint proves the mechanism exists, but does
not exercise recovery from later resumable checkpoints in the same bounded
workflow.

## Decision

Add a `run_grouped_matching_replay_fault_matrix` harness that runs the existing
public replay profile against a fresh SQLite database for every non-terminal
partition checkpoint. Each run must reproduce the uninterrupted effect digest,
preserve strategy/application parity and the adversarial mutation guard, leave
zero duplicate effects, and drain queued/running state.

## Consequences

- Later checkpoint corruption or skip logic is exercised without changing the
  production matching contract or persistence schema.
- Each matrix case is isolated, deterministic, and easy to replay locally.
- The matrix remains synthetic SQLite evidence; it does not prove PostgreSQL,
  distributed workers, queue failure, throughput, or production SLOs.

## Verification and rollback

The focused replay/adversarial suite passes 10/10, including fault points 1,
2, and 3. Removing the harness, test, ADR, manifest entry, and evidence is
reversible; no migration or persisted-data change is involved.
