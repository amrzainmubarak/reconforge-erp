# ADR0866: Reuse native query plans while retaining exact financial checks

Date: 2026-10-18

Status: Accepted implementation; final-source operation and recovery gates pending.

## Blocking evidence

The unchanged15s browser gate refuses the sixth economic operation of the actual
zero-leg remainder cycle: the owned cost-restoration inverse. The same genuine
sequence on pinned PostgreSQL17.11,2CPUs/1GiB takes21.234s instrumented, including
19.609s deferred checks. It calls `irp_scope`10382 times, `irp_canonical`71645
times and `fr_snapshot`96 times. JIT-off alone takes18.859s; a scope-only plan
experiment18.844s. Neither is accepted as a completed repair.

The three-query experiment takes13.109s, including11.610s deferred checks.
Every closure still executes. These are controlled synthetic diagnostics, not
throughput claims or substitutes for the mandatory actual browser operation.

## Decision

Add revision0150 after149. Preserve149 and every older migration. Keep the exact
scope and financial-review SELECT expressions inside STABLE invoker PL/pgSQL
functions, whose prepared expressions can be reused. Retain the existing
canonical equations with C-ordered object keys, ordinal arrays and PostgreSQL
scalar text in IMMUTABLE STRICT PL/pgSQL recursion. Preserve NULL behavior,
function identity, arguments, result types, ownership, ACLs and search path.

No authorization result, financial row, original packet or source proof is
cached. Every current predicate, full source/history check and financial trigger
continues to execute. No transaction bypass, GUC admission flag, birth-time
cache, timeout increase, new grant or financial mutation is added. Keep JIT at
its existing setting. This narrowly supersedes ADR0862's implementation choice
to leave IRP helpers untouched, based on the witnessed operation blocker; its
financial, custody, authorization and independent-verification requirements stay.

PostgreSQL documents [PL/pgSQL plan reuse](https://www.postgresql.org/docs/17/plpgsql-implementation.html#PLPGSQL-PLAN-CACHING)
and [STABLE/IMMUTABLE snapshot behavior](https://www.postgresql.org/docs/17/xfunc-volatility.html).
Preserve the existing volatility classifications and verify live scope changes;
prepared plans do not authorize reuse of a previous result.

## Upgrade, legacy installation and rollback

Preflight the exact three old bodies and execution profiles before replacement;
postflight all three new profiles. Unknown body, definer, overload, strictness,
configuration or other execution drift refuses. CREATE OR REPLACE preserves OIDs,
owners and grants. The financial-reporting installer recognizes a complete150
profile before its DDL and restores only its exact known snapshot definition
afterward. A partial or unknown150 installation cannot fall back or self-repair.

Downgrade150 to149 restores the exact original SQL definitions, with preflight
and postflight, without changing any business row or relation. It restores the
observed latency risk, so retain the failed operation evidence. Existing149
data-retention and destructive-downgrade guards remain unchanged.

## Required evidence

Actual ordinary-role differential checks use the old SQL outputs before upgrade,
including NULLs, decimal lexical forms, Unicode and a real posted plan. Reuse a
live prepared session while changing scope GUCs and upgrading functions. Verify
financial-review bytes, all347-table row hashes, non-function catalog hashes,
OID/owner/ACL and execution attributes, legacy reinstall, exact rollback and old
acknowledgement readability. Poisoned body, definer and overload cases must refuse
without altering the poisoned catalog. Repeat actual zero and foreign operation,
identity/foreign independent-I/-I-O proof, populated restore and coherent CI.
