# 0855 — Versioned enterprise cost, FX and approved-time ownership

Status: accepted engineering contract; capability acceptance requires executed gates.

## Entry gate

Milestone M1 starts from `542d42822d88613d784a32392416b7acd5e14c2d`, the
actual Wave5 quality/source head. CI38288602928 completed44/44 jobs; mandatory
native admission completed18 partitions/54 sessions/1528 cases with0 skip,
xfail or xpass. Docker, CodeQL, five manual security jobs, current source
archives and populated recovery passed. Original closure SHA256:
`07bc3fd44b6de8b52d77ed35a8624c97cdfecaa754fbafea666dee7aa82c7f98`.
This acceptance is distinct from comparative performance, which is false and
deferred by the human. No local benchmark or profiling window is authorized now.

## Ownership and compatibility

The modular monolith keeps the existing GL, currency registry, exact conversion,
inventory/FIFO, identity, current grants, financial periods, budgets, audit and
outbox. Each new command owns its original operational and native financial
effects in one transaction. Old ME1, IC1, FX1 and procurement contracts remain
valid; no existing posted history is relabelled or changed. Agent-owned routes,
schemas, domain services, pages and tests are integrated through root-owned
registration and financial participant admission.

Agent1 owns ME2 manufacturing and necessary version-aware ME1 extensions.
Agent2 owns IC2 foreign-currency intercompany operations. Agent3 owns HC1
people/project time and nonstatutory wage accounting. Root owns shared API,
posting admission, runtime registry, Studio navigation, migrations and CI.
New migration numbers are138(ME2),139(IC2),140(HC1), following136. The rejected
experimental137 is not installed or reused. Numeric revision identifiers and
the actual number of installed revisions are separate facts.

## ME2: accountable cost and quality disposition

Labor and overhead use bounded immutable allocation claims against original
native posted positive expense debit lines. Claims bind tenant, workspace,
organization, entity, effect, line and captured currency policy. Original
effect verification and cumulative allocation capacity are enforced under
locks and deferred SQL constraints; the original cannot be independently
reversed while claimed. Transfer accounting is DrWIP/Croriginalexpense.
There is no unsupported cost created by an arbitrary amount-only journal.
The eligible cost pool and routing revision freeze before first output.

Uninspected production remains held WIP. Only accepted inspected units create
native finished-goods receipts; rejected units require explicit abnormal-loss
disposition. Quantities and minor units conserve across every partial stage,
with the final stage consuming exact residuals. A versioned source-owner guard
must prove material+labor+overhead=finishedgoods+loss+retainedWIP. ME1's existing
material-only closure is not bypassed by an unrelated additional journal.
Planning demands precede supply claims and are distinct from existing gross
requirements created after component reservation. Full MRP/capacity scheduling
is not claimed until actual connected shortage/sourcing/receiving cycles pass.

## IC2: original books and explicit reporting authority

The initial expansion is a qualified paired intercompany trade-account owner,
not a claim of a general foreign AP subsystem. Each party has its own native
journal, functional currency policy, rate source/effective date and original
receivable/payable account. One explicit transaction currency controls the
cumulative settlement quantity. Realized and unrealized FX use the existing
exact conversion policies, retained carrying amounts and source-owned effects.

A distinct native group adjustment entity, reporting currency, journal and
reviewed account/rate map are mandatory. Translated management membership,
CTA and original native eliminations are separately explained and balanced.
Reports verify source effects and current authority for every contributing
entity; a report map cannot enlarge entity grants. The first scope excludes
ownership/NCI, investment elimination, profit in stock, hyperinflation and
blanket IFRS/US GAAP or statutory compliance.

## HC1: approved time, privacy and wage liabilities

Personnel masters and effective hourly employment are explicit operating
objects; employees are not AP suppliers. Approved project time binds its
original employee, employment/rate version, project dimension, dates and
independent human approval. Earnings use versioned exact HALF_EVEN per-employee
gross arithmetic, then deterministic cumulative project allocation and final
residual conservation. This nonstatutory rule is distinct from the captured
native ledger currency policy.

An immutable claim history and a unique active claim prevent the same approved
time being reserved by multiple payruns. Financial posting irreversibly consumes
that original full time entry once. Cancelling an unposted payrun preserves its
claim history and appends an authorized release; only released, unconsumed time
can be claimed again. No deletion, silent reassignment or duplicate wages is
allowed. Budget Reserve/Consume/Release must be closed against HC1 source and
the native accrual; the procurement-specific BPC1 guard is not sufficient.
Accrual is Drprojectexpense/Crpayrollliability; partial/final payment is
Drliability/Crcash. Every financial phase requires three distinct persisted
humans and current authority. Personnel fields have explicit separate access,
and audit/log payloads omit private earnings details.

## Acceptance and reassignment

Each slice requires real Database→domain→API→authority→audit→Studio→native
posting→independent verification, direct SQL refusal, lost-response replay,
revocation, concurrent source claims and populated restore. Independent financial
oracles use stdlib integer/Fraction inputs and original exports without importing
application calculations. Backend availability is explicit; PostgreSQL execution
does not imply SQLite operating support. Missing adapters remain a matrix gap.

Only targeted invariant, migration, compile/type and integration checks run
during implementation. Full gates run on a frozen integrated commit. After a
complete slice, each agent reviews another stream and proceeds to the next
ready connected capability. All countries remain the target; this baseline has
zero proven activated statutory packs. Main and the original dirty files remain
protected. New commits use Amr and milestone PRs remain drafts without merging.

## Personnel SQL credential boundary

A freely SET-able actor/session GUC and a persisted user ID do not authenticate a
direct SQL reader. Private HC1 tables therefore require restrictive FORCE RLS
with membership of `session_user` in a safe NOLOGIN personnel role. Ordinary
finance runtime logins receive no automatic membership. A separately configured
personnel login uses the same database endpoint and existing tenant boundary,
native finance adapter and server identity; no second identity engine is added.
The private API pool is optional and absent by default. Sensitive reads and
commands require a current human, explicit private permission and stronger
authentication, followed by current persisted permission checks. No request can
select its credential or factory. Missing private configuration is unavailable.

The dedicated DB credential is a trusted backend privilege, not per-human DB
authentication. Possession or administrative misgrant of that credential is not
claimed safe. Native tests must verify ordinary SQL refusal even with blanket
table grants and forged actor GUC, current authority and populated restore role
prerequisites. Backup restore must not silently omit the required role boundary.
