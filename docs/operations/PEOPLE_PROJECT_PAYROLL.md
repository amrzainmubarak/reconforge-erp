# Operating the HC1 nonstatutory wage cycle

HC1 records hourly management wages and project expense in the existing native
ledger. Supported statutory country payroll/tax/pension packs: zero. Recorded
cash settlement is a GL operation; it does not initiate a bank transfer.

Install the ordered PostgreSQL migration chain through
`0140_pg_people_project_payroll`. PostgreSQL is required; Community SQLite
payroll is explicitly unavailable. Back up and restore the existing database
using the normal platform procedure before an upgrade.

The migration creates or validates the fixed `reconforge_personnel_runtime`
NOLOGIN group with no superuser, RLS bypass, role creation, database creation,
inheritance or replication privileges. It grants no membership automatically.
Provision a dedicated nonowner LOGIN with only required table privileges and
grant this group to that login. The ordinary finance LOGIN must never be a
group member. Provide its secret through `RECONFORGE_PERSONNEL_POSTGRES_DSN`
to the trusted server environment; never put it in a report or browser input.
Both connections must explicitly address the same host, port and database,
with different authenticated users. Missing private configuration returns
503 after human admission, with no ordinary connection fallback.

Configure current human permissions and workspace/organization/entity grants.
Personnel registration requires `people_project_payroll.personnel` and
`read_sensitive`. Approved time requires an independent enabled human with
`approve_time`; neither submitter nor linked employee identity may approve.
Financial preparation, review and posting require three distinct enabled
humans with the corresponding HC phase and native finance/budget permissions.
The route inventory lists the complete phase contracts. No new default roles
or automatic permission grants are installed by this module.

Create the native Expense, Liability and Asset accounts in the original
journal chart, an existing Project dimension and its values, an open period,
and an independently approved budget. Use Studio to register employees,
capture immutable effective hourly agreements, bind projects, submit whole
minute-based time documents and independently approve them. Prepare a payrun
from approved time; this reserves budget. Review its verified source, then
post to consume budget and claim time atomically with the original native GL.
Prepare, independently review and post partial/final employee allocations to
reduce the original liability against cash. Individual payments are private.

If a response is lost, use the retained exact command and the same human.
Its immutable acknowledgement describes the original command phase; load the
separate current source to observe later review/posting. Do not generate a
new command to guess whether an earlier financial effect committed.
Cancel only an unposted accrual. Cancellation keeps history and releases its
budget/time claim before a later payrun may re-claim the same approved source.
Consumed time never becomes available for another wage accrual. Posted
correction, payment cancellation and partial-time allocation are unavailable
until separate source-owned contracts are implemented.

Names, rates and individual wage allocation require the private login and
current human sensitive-read authority. Ordinary aggregate finance reads do
not return these fields. Audit/outbox messages retain digests and original
scope without raw salary/name data. A dedicated personnel credential remains
a trusted backend privilege, not individual human database authentication.

Database pg_dump archives do not back up cluster roles. Provision the safe
group and dedicated LOGIN membership separately before restoring a database.
Verify the original history, RLS, grants and source/native effect relations;
then prove the ordinary LOGIN still cannot read private tables even with a
forged actor selector. Never broaden that login's membership to make a
restore pass. Empty HC tables can downgrade; populated source history refuses
destructive downgrade and requires a verified backup/restore path.

The standalone standard-library verifier
`tests/verify_people_project_payroll_oracle.py` requires a separately trusted
raw evidence SHA256. It recomputes hourly Fraction earnings, project residuals,
native debit/credit and original claim/budget conservation. Export evidence
only through the authorized private path and classify synthetic fixture
exports separately from real restricted personnel data. The verifier does
not assert country compliance, bank execution, audit-chain recomputation,
production readiness or benchmark acceptance.
