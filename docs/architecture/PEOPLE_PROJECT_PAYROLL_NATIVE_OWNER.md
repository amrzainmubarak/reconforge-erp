# Nonstatutory workforce source contract HC1

Employee names, effective hourly rates and employee wage allocations live in
separate private tables. Every table has FORCE RLS. Private tables require the
actual authenticated `session_user` to be a member of the fixed safe NOLOGIN
`reconforge_personnel_runtime` role, in addition to current scope and an enabled
human's persisted `people_project_payroll.read_sensitive` grant. An actor GUC
selects current authority inside that trusted backend connection; it proves no
database authentication. Ordinary finance credentials cannot cross this role
boundary by forging the selector. Dedicated personnel credentials remain a
trusted backend privilege and must be protected independently.

An administrator configures a separate nonowner personnel LOGIN in the same
database and grants explicit runtime table privileges and private role
membership to that login only. The migration never grants membership to an
ordinary runtime login and refuses an unsafe existing role. The API's internal
operation selects its connection factory. Missing private configuration is an
explicit unavailable capability; there is no ordinary-connection fallback.

Employment versions are immutable and cannot overlap. Time captures the
effective version, exact integer UTC minute intervals, original Project
dimension links and an independent approver. The time submitter and linked
employee identity cannot approve. The first contract consumes whole approved
time documents and allows one current Active or Consumed claim per qualified
time source. Claim history and Claim/Release/Consume events are append-only.
An unposted cancellation releases its native budget reservation before another
payrun may claim the same original digest. Consumed time cannot be released.

Hourly earnings use integer numerators over 60 and HALF_EVEN once per employee.
Canonical project cumulative rounding allocates residuals without losing an
employee's final minor unit. This versioned wage rule is separate from the
native currency registry's precision and monetary rounding. Original rates,
approved time, project amounts and employee gross are independently recomputed
by the deferred SQL closure before admitting any financial phase.

HC1 prepares native project-expense debit lines and an aggregate wage-liability
credit while recording native Budget Reserve. A separate reviewer validates
the original native content, and a third human posts Budget Consume and the GL
effect atomically. HC1P reduces the original wage liability against cash with
private employee allocations and exact cumulative overpayment refusal. Each
source phase retains its original command acknowledgement, audit and outbox;
audit payloads contain digests rather than personnel names or pay amounts.
Generic posting requires the exact source participant. Generic reversal cannot
detach consumed time, original wage liability or posted cash settlement.

The initial scope is **nonstatutory management wage/time accounting**. Statutory
country packs supported: **zero**. It does not execute bank payments, calculate
tax or social contributions, or establish national payroll compliance. SQLite
payroll remains unavailable. Payment creation currently refuses a drifted
native monetary registry binding rather than reinterpret the original policy.
Posted correction, payment cancellation and partial-time claims need separate
reviewed source contracts.

The development gates over accepted revision136 plus this owned schema
executed fifteen native cases without skips, covering the complete cycle,
SQL bypass, race, revoked authority, replay, cancellation and worker delivery.
Four later account-role cases passed without skips: original Expense/Liability/
Asset chart roles, rollback of an invalid reserve, source-used role mutation,
unreferenced deletion, and metadata maintenance without HC source SELECT.
The populated restore case preserved every reconforge table's row fingerprint
and the HC catalogs/policies, preserved personnel role separation, replayed
the original immutable command receipt, and settled the remaining cash. It
does not independently fingerprint every function, ACL or constraint.

Ordered migration140 integration executed two real PostgreSQL TestClient
cases with an HTTPS request scheme and both database roles. This establishes
authenticated API integration, not socket/certificate TLS or browser execution.
Twelve Studio component/data cases and TypeScript passed. The real browser
contract is implemented but awaiting execution by the common owned TLS/restore
runner. These source-specific gates do not qualify a full integrated release
or any performance comparison.
