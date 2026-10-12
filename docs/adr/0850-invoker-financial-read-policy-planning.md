# ADR0850: Preserve financial RLS authority while reducing recursive planning

Date: 2026-10-10. Status: candidate; integrated acceptance remains required.

## Observed problem

The unchanged PR129 source has repeated planning of nested financial line and
dimension read policies. An owned PostgreSQL17.10 diagnostic records approximately
18.6 seconds of accumulated nested planning during 20 actual two-line postings.
Planning totals are overlapping server work, not transaction wall time. The
highest-cost dimension queries plan tens of milliseconds while execution takes
milliseconds across the population. PBKDF2 remains a separately measured client
CPU contributor; password policy is retained.

## Decision

Reuse line IDs already read through the authoritative RLS scope when reading
dimensions and checking required-dimension coverage. Preserve current required,
active and organization checks, and support both tuple and mapping database rows.
Migration0129 replaces only two read-policy parent predicates with STRICT STABLE
PL/pgSQL SECURITY INVOKER helpers, using an explicit pg_catalog search path and
qualified authoritative parent tables. This keeps parent privileges and RLS
checks at execution; there is no authority cache or elevated security owner.
FORCE RLS, write policies, relationship locks, monetary precision, posting source
closure and immutable audit/outbox are unchanged.

The volatile scope settings must be evaluated afresh on every execution, even
when PostgreSQL reuses a prepared plan. STABLE uses the outer statement snapshot;
the existing parent relationship and write guards remain responsible for write
concurrency. The helper is not a promise of authority across transactions.

## Validation and limits

Nine owned native cases pass at a4ffa822 without skips: prepared execution across
tenant/workspace/organization/entity scope changes; malformed legacy scope; parent
SELECT revocation after plan reuse; exact retained WITH CHECK parity; migration
rollback/upgrade; late required-dimension admission with complete, missing and
empty coverage in tuple and actual dict_row modes. The broader finance scope and
posting suite previously executes36 cases without skips for the line-ID change.

The diagnostic helper experiment records9.322s/20 postings and9.55s nested planning
versus the earlier18.6s planning sample. Those overlapping diagnostic samples
do not constitute performance acceptance. Final acceptance requires at least
three independent fresh populations per variant, real warmup, alternating order,
identical resources and durability, raw latencies and independently checked money.
Changing join/from collapse limits to1 did not reduce planning sufficiently;
production retains the defaults. JIT counts were0; no JIT tuning is justified.

## Rollback

Restore the exact authoritative parent EXISTS read predicates, then drop the two
helpers. Preserve all financial rows and the original WITH CHECK policy text.
The populated native rollback gate verifies this order without CASCADE.

## References

- [PostgreSQL17 row security](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).
- [PostgreSQL17 function volatility and statement snapshots](https://www.postgresql.org/docs/17/xfunc-volatility.html).
- [PostgreSQL17 planning instrumentation](https://www.postgresql.org/docs/17/pgstatstatements.html).
- [PostgreSQL17 explicit joins](https://www.postgresql.org/docs/17/explicit-joins.html).

No PostgreSQL/client dependency change, distributed service, permission bypass
or persistent cache is introduced.
