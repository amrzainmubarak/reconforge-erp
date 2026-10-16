# ADR0862 — Fixed monetary Stock originals and partial corrections

Status: implementation contract; native149 and complete M7 acceptance pending.

## Decision

Keep accepted375 Stock/CR1/CR2, allocation, FX and transfer-cost v1/v2/v3
interpretations. A new Stock source version is fixed at creation. Commercial
quantity, unit price, discount and AR remain in transaction currency F; FIFO,
COGS and GL remain in functional currency L. No functional unit price is derived
by dividing an aggregate. Identity currency requires identical captured policies
and no exchange-rate object. Foreign rates retain their original provenance.

At native invoice preparation, bind actual Stock delivery/consumption evidence,
the quantity/pricing AR line, the existing FX recognition plan, tax components,
original account/dimension roles and the captured registry in one immutable
origin. Seven additional FORCE-RLS relations own the new plan/history/witness
and acknowledgement contract; they add no parallel GL or inventory ledger.

Use `remaining-dual-currency-v1` for component cuts in F and L, current carrying
release, refund entitlement and cash release. Money uses captured HALF_UP and
original FIFO uses HALF_EVEN, with complete final residual release. Historical
component-versus-current-carrying differences have explicit alignment legs.
Collection after a posted credit must release the current credited AR basis.
A refund or merchandise inverse copies the latest eligible original effect and
its witnesses. Reverse an active closing revaluation before a new historical
correction. A zero functional turnover creates no journal, while keeping exact
positive transaction cash, three-person duties, current authority and evidence.

Public invoice/aging/exposure projections read the governed `ar_balance` and
actual AR rows in one outer SELECT snapshot through two STABLE invoker helpers.
PostgreSQL documents this calling-query snapshot for STABLE functions and fresh
internal snapshots for VOLATILE functions. Native write/phase/physical callbacks
are separate VOLATILE helpers and cannot use a STABLE report result as proof of
writes made in the same command. See the official
[PostgreSQL17 volatility contract](https://www.postgresql.org/docs/17/xfunc-volatility.html).
The reporting role needs no new write privilege to read an invoice.

Preserve all16 affected accepted function OIDs, owners, ACLs and execution
attributes by exact-body-pinned `CREATE OR REPLACE`. The existing cost-layer
SECURITY DEFINER retains its security context; only its immutable signed-history
equation gains actual CR3 restoration terms. All new helpers execute as caller.
The new cost-v4 envelope retains both old and new correction families and zero
consumption witnesses. Its equation includes those signed quantities/values;
it never presents corrected observed rows as an old cost envelope.

An existing149 installation must pass complete function, trigger and FORCE-RLS
verification before any retained installer runs. A genuinely absent149 namespace
keeps the old installation flow; any partial footprint refuses. Downgrade refuses
even a newly born unrecognized monetary Draft, new FX original or retained new
evidence before destructive DDL. An empty148/149 round trip must restore exact
old body bytes and metadata.

## Acceptance boundary

Required proof includes actual identity and foreign Stock originals, repeated
partial returns, a second collection after credit, partial refunds and copied
inverses, credited-basis closing/reversal, real zero-functional cash, ordinary
SQL abuse, concurrency, stale permission/scope refusal, atomic interruption,
real Studio HTTPS and populated restore. Independent qualification reads91
actual source tables; old79-table readers are unchanged. Synthetic configured
tax rules establish no country's statutory compliance.

Component tests, collected native cases, tables, APIs and screens do not close
M7.7/M7.9. Only one frozen source with actual native/HTTPS/restore, independent
financial evidence and mandatory CI closes the declared scope. Heavy comparative
benchmarks and the next major domain remain deferred until functional closure.
