# ADR 0883: Isolate per-run policy denials within one discovered page

Status: proposed. Date: 2026-10-28.

## Context

An unknown-amount policy denial can end `process_once` and stop unrelated work.
The active-run query returns a bounded page, so simply continuing that page
does not ensure progress through further pages or across restarts.

## Decision

Separate a genuine policy decision denial from supplier, manifest, evaluator
and audit failures. The reconciliation worker reports a per-cycle `denied`
count and continues with other runs and tenants in the current page; errors
that prevented evaluating or recording the decision remain visible. Log a
redacted warning that later pages may be delayed. The shared guard preserves
its earlier exception behavior for callers that do not opt into typed denial.
After a claim transaction commits, matcher exceptions, including exceptions
with denial, authorization or busy types, follow execution failure handling;
busy before claim remains a lease skip.

This is partial isolation, not durable fair discovery. A page full of denied
jobs can still starve later pages; discovery-level authorization failure still
stops the cycle. The count and warning are not a durable per-run denial audit.
`ReconciliationWorkerRunSummary.denied` has a default and is propagated by
the scheduler; it changes dataclass-to-dictionary representation. No claim is
made that external closed-schema consumers accept the new field. Operators
must not treat the count as proof that exposure values or stored policies are
correct. See `docs/execution/WORKER_DENIAL_FAIRNESS_2026-10-28.md` for the
remaining keyset, persistence and recovery requirements.

## Verification and rollback

Focused tests cover policy denial versus supplier/evaluator/audit errors,
cross-tenant continuation, no claim for a denied run, summary aggregation,
and exceptions before and after claim including a retained checkpoint.
PostgreSQL native tests and full hosted gates remain separately recorded.
Reverting this change restores the previous worker-loop interruption behavior;
it does not change stored financial records or resolve the original blocker.
