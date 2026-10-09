# ADR0843: Conserved enterprise orders and frozen financial captures

Status: accepted for experimental contracts,2026-10-09; final integrated
acceptance remains pending. Start at PR126 exact21b4b8a2, preserving PR125/124
and main. Three independent worktrees own Sales Commerce, Procurement and
Financial Reporting. Lead owns shared migration order, authority, finite grants,
UI transport, CI and measurements. Reuse native engines; no new dependency.

Sales retains one immutable commercial parent with up to1000 priced item/location
lines. Partial native tranches reuse stock reservations, FIFO/COGS, AR and Cash.
Deferred source/native closure conserves ordered/reserved/delivered/invoiced/paid
amounts. Three independent current humans publish each financial stage. Parent
partial collections mean paid tranches; individual AR invoice partial payment
remains a separate capability.

Procurement retains one native multi-line PO with immutable per-line quantities,
warehouse and policy provenance. Partial reviewed inventory receipts feed native
supplier invoices with multiple allocations. Heterogeneous units have no summed
header quantity. AP accrual and FI1 installment settlement remain authoritative.
CAS and immutable command evidence protect exact quantity and cost conservation.

Reporting captures complete database-owned source membership in one statement
under its MVCC view. Bounded native verified batches fold that frozen membership;
immutable summaries and authorized cursor evidence preserve exact totals and
chain digests. Maximum IDs and long-lived xmin are not historical identities.
Legacy bounded statements retain refusal behavior. Capture grants no posting power.

Migrations0116→0117→0118 follow dependency order. Empty downgrade removes dependent
triggers before functions; populated history refuses destructive downgrade. Native
backup/restore retains evidence. No CASCADE or weakened accounting constraint.

Studio commands deeply clone/freeze nested JSON before assigning a retry key;
money and quantity stay exact strings. Unknown outcomes retain the same key,
payload and expected version. Typed bounded query values encode separately from
scoped paths, preserving namespace, current identity and CSRF.

Benchmarks use genuine native prepare/review/post cycles, an independent integer
oracle, a nonowner role without RLS bypass and alternating reads over identical
immutable effects. Client execute counts differ from server-internal statements.
Request units, latency and resource caps are explicit. No vendor superiority,
statutory cash-flow, global FX/tax or production claim follows from a bounded test.

Integration found an unrelated-item chronology rejection in the native receipt
kernel. Additive0119 scopes application and SQL admission to the locked item pool
across warehouses; generic valuation intersects item and lot. Same-item date and
reserved-number ordering, consumed-layer history and all original guards remain.
Historical0100/0108 SQL stays frozen.0118 uses the31-character revision
`0118_pg_financial_report_capture`, within the existing Alembic version column.

The first integrated hosted run retained two concrete failures: an additional
JSON decoder outside the approved parser inventory, and scope inputs accepting
edits before asynchronous identity defaults arrived. Reuse the existing retained
snapshot decoder and disable those inputs until identity is ready. Constant SQL
assembly is made explicit without changing emitted SQL or suppressing Bandit.

Each native CI shard installs its own locked runtime and PostgreSQL/Redis services
and consumes no Python/web job artifact. Remove that unnecessary dependency so
all eleven shards remain observable after a Python failure. Both Python versions
also complete independently. All forty native commands, the four-worker matrix
ceiling, fail-closed aggregate and separate required Python/web checks remain.
