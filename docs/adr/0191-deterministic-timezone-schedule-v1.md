# ADR 0191: Deterministic Timezone Schedule v1

- Status: Accepted
- Date: 2026-07-29
- Decision owners: ReconForge maintainers
- Scope: P3-ENT-005 schedule semantics before persistence or network delivery

## Context

A durable scheduler must produce the same occurrence identities from the same schedule version and cursor while treating daylight-saving gaps, ambiguous local times, long outages, and misfires explicitly. A generic cron string does not by itself define those semantics and would introduce a new parser dependency before the required behavior is bounded.

## Decision

The v1 schedule contract supports daily and weekly local-wall-clock schedules with:

- an explicit IANA timezone and directly declared `tzdata` runtime dependency;
- whole-second UTC start/end/cursor timestamps;
- a selected first or second occurrence for ambiguous DST times;
- explicit counting and skipping of nonexistent DST wall times;
- `skip`, `fire_once`, and bounded `catch_up` misfire policies;
- a 1–100 catch-up ceiling and a configured lookback review boundary; and
- SHA-256 occurrence identity over schedule ID, schedule version, and UTC occurrence.

Catch-up advances only through the last dispatched occurrence when backlog remains. Skip and fire-once advance through the evaluation time. A lookback beyond the configured boundary fails for operator review instead of silently losing occurrences.

## Consequences

- Schedule evaluation is deterministic, network-free, and independent of persistence.
- DST behavior and misfires are visible in the result rather than inferred from host local time.
- Cron expressions, monthly/calendar rules, PostgreSQL persistence, leader coordination, job submission, notifications, and external delivery remain outside this slice.
- The direct timezone-data dependency avoids relying on an operating-system timezone database or a transitive package.

## Rollback

The new module has no existing call sites or schema effects and can be removed with its tests and direct dependency. Persisted schedule formats must not be introduced until a later versioned migration binds this contract.
