# ADR 0882: Explicit unknown reconciliation worker exposure

Status: proposed; per-page denial handling is extended by ADR0883. Date: 2026-10-28.

## Context

The shared service-worker guard previously treated `amount=None` as no override
of its supplied policy context. That behavior is also used by discovery and
other worker callers. A reconciliation run whose amount is actually unknown
could therefore inherit an unrelated supplier amount in a bounded policy.

## Decision

Add an explicit unknown-amount token to the shared worker guard. Omitted and
`None` amounts retain their existing meaning for compatibility. The
reconciliation worker passes the token at execution checks when the run amount
is unknown, including the recheck before claim. The policy then receives an
unknown amount and denies it when a bound requires one. Discovery and other
workers retain their previous contract. A rejection remains explicit, before
claim, rather than being recorded as a successful or skipped job.

This is a limited safety guard, not proof of a correct financial exposure.
`process_run` still accepts a caller-provided non-None amount, stored legacy
amounts can be context-sensitive, and mixed currency lacks a defined conversion
policy. A denial can stop the current `process_once` loop; per-run failure
isolation needs its own observable contract. The change deliberately makes a
direct reconciliation execution with unknown amount fail under a bounded
policy where an unrelated supplier amount previously allowed it.

## Evidence and rollback

Policy and worker tests exercise omitted, explicit `None`, zero, boundary,
unknown, discovery, reauthorization and no-claim behavior with an actual policy
engine and a repository test double. PostgreSQL-native verification and final
source CI remain separate. Reverting the explicit token restores the unsafe
inheritance behavior for unknown reconciliation amounts; keep existing jobs,
records and checkpoints, and do not represent rollback as financial approval.
