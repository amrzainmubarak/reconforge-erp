# Atomic intercompany service charge and native group adjustment

This experimental PostgreSQL owner composes the existing native FinanceCore,
posting and financial-reporting engines. Configure three distinct active entity
scopes in one organization/workspace with one currency: the seller, the buyer,
and an explicit consolidation adjustment scope. That third scope is a configured
book for management reporting; the feature does not establish a legal company,
ownership percentage, tax treatment or statutory consolidation policy.

Use organization/workspace request context without an entity header. All three
entity grants remain mandatory. The route rejects a supplied single-entity
context rather than widening it. Read, prepare, review and post require the
corresponding `intercompany_operations.*` and native FinanceCore permission,
current persisted human identity and recent reauthentication for mutations.

Recognition debits seller IC receivable and credits seller service income;
buyer expense and payable post in the same transaction. Each exact positive
cash installment debits seller cash/credits receivable and debits buyer
payable/credits cash. Every operation is prepared, reviewed by another human,
then posted by a third human. Retry a lost acknowledgement with the unchanged
command, actor and request; retained responses still require current source
and complete journal-turnover authority.

After required installments, prepare the final group adjustment. Its actual
native entry debits original intercompany income and credits original expense,
then debits remaining payable and credits remaining receivable. Original
seller/buyer books remain unchanged. The posted group adjustment seals this
source against subsequent installments. At most32 installments are supported.
An inverse is not provided by this bounded cycle; public native reversal of
an IC1-owned effect is refused.

Use three existing independently reviewed FinancialReporting maps, explicitly
classifying the five native accounts, to report all three books as of the same
date and period. Every original and adjustment effect must be included. The
report folds exact account balances and retains every native posting line,
entity report and digest for drill-down. Whole report turnover is admitted by
current native and intercompany read policies before exposure. Net cash
movement is reported without inferring statutory cash-flow categories.

The evidence endpoint retains canonical source and plan JSON, every native
snapshot/digest/effect, and the three human audit/outbox phases. The owner SQL
independently reconstructs the exact original, installment and residual
equations, so a half-reviewed or half-posted operation cannot commit through
direct SQL. Native namespace dispatch returns before new protected owner
tables for ordinary unrelated entries and events.

Locks follow command advisory, shared fiscal period, canonical workspace
currency binding, sorted current entity parents, original source, retained
plan and sorted native entries. Read and mutation paths share source-before-
plan order. Arbitrary direct SQL callers can still contend; no zero-deadlock
claim is made for unsupported lock orders. Empty additive schema downgrade
is permitted; populated history refuses destructive downgrade. Use the
existing populated backup/restore gate before delivery.

Native, HTTPS/Studio, independent oracle and populated restore acceptance
remain pending until their exact fixed-source packets are retained.
