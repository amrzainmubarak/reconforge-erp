# ADR 0849: Historical foreign receivables, effective tax and realized FX

Status: Accepted for the experimental PostgreSQL slice; integrated acceptance remains evidence-bound.

## Context and accounting contract

Native AR retains the customer's source currency. The existing native posting
owner retains the legal entity's functional currency and supplies one immutable
double-entry ledger. A source-specific owner must close those representations
atomically without adding a ledger, exchange-rate engine or authorization store.

The FX1 owner composes the existing `Money`, `ExchangeRate`, currency registry,
`FinancePolicyStore`, native AR and native posting participants. Recognition
retains the original reviewed spot rate, source and explicit UTC observation on
the accounting date. Partial settlements release the cumulative original-rate
AR basis and recognize the difference against functional cash as realized gain
or loss. This implements the narrow recognition/settlement model described in
[IAS 21](https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2024/issued/part-a/ias-21-the-effects-of-changes-in-foreign-exchange-rates.pdf?bypass=on)
paragraphs 21 and 28–29; it is not a statement of IFRS compliance.

Tax components are explicitly reviewed net-exclusive fractions, selected for a
retained country, accounting date and transaction class. Each retains effective
bounds, policy ID/version, source and content digest. Synthetic country examples
are not jurisdiction tax rules. Tax calculation occurs in source minor units;
functional allocation uses converted cumulative prefixes so component rounding
cannot detach net revenue plus tax liabilities from gross functional AR.

## Native ownership and lifecycle

The owner reserves the `FX1-` namespace in native invoices, receipts and journals.
An additive source, plan, review, posted link and command history capture the
complete financial interpretation. Recognition prepare creates a submitted
native invoice and draft native journal. Independent review approves that
invoice and validates the journal. A third distinct human posts the journal.

Each settlement has its own reviewed plan and retained rate. Its third-human
post creates exactly one native foreign receipt/allocation and functional
posting in the same caller-owned transaction. Failure after any participant
effect rolls back the complete transaction. Native AR totals/status, original
tax/revenue, exact snapshot, journal turnover, native receipt, posting effect,
actors, immutable acknowledgement, audit and outbox close together. SQL uses
NUMERIC equations independently of Python's exact money calculation.

Preparation/review/posting require current persisted finance and AR grants,
current human identity, scoped authority and recent step-up. Reads and retries
authorize the original source gross in both original precisions and each
emitted journal's complete debit turnover. A small allowed receipt does not
grant permission to disclose its larger original invoice or tax basis.

## Locking, evidence and compatibility

Supported mutations acquire the command advisory lock, accounting-period share
lock, existing canonical currency binding admission lock, native customer,
native invoice, FX source, FX plan and native financial participants in that
order. `FinancePolicyStore.lock_binding` exposes the same existing exclusive
key; it does not change binding writer protection or capture a new historical
interpretation on retry. Detail/evidence take native customer and invoice
before source and plan. The concurrency test observes actual
`pg_blocking_pids` and completes recognition and settlement with that order.
Arbitrary SQL can choose conflicting locks and receive a PostgreSQL abort;
the complete authorized command remains the retry unit.

All five owner tables use FORCE RLS. Current-human admission and deferred source
closure deny SQL-only detached AR transitions, arbitrary allocations and native
journal publication. Closure dispatch checks reserved FX event types before
querying owner tables, preserving unrelated Outbox workers' least privilege.

Evidence returns exact canonical source, plan and native snapshot JSON strings,
three SHA-256 seals, native effect identity and audit/outbox phase references.
Studio independently hashes their exact UTF-8 bytes with WebCrypto, uses BigInt
for totals and requires three distinct human phases. Source JSON monetary
fields are integer minor-unit strings at the API boundary, with retained
currency precision. Source and journal history remain immutable.

Migration 0128 is additive. Empty tables may downgrade; populated evidence
refuses destructive downgrade and requires a verified populated backup/restore.
The isolated development predecessor is 0125; the integration owner chains it
after the accepted commercial and supply migrations. Existing local Community
accounting and commercial collection boundaries remain unchanged.

## Explicit limits and validation

This slice handles standalone foreign service/customer invoices, at most eight
net-exclusive tax components and 200 sequential operations after recognition. It does not add
foreign inventory sales, AP FX, external payment execution, compound/inclusive
tax, automated jurisdiction policy selection, rate feeds, original invoice
source reversal or consolidation. A settlement converting to zero
functional cash is refused explicitly. Values and complete debit turnover are
bounded by 9,000,000,000,000,000,000 minor units and rates by exact bounded decimal
text. Functional journals retain the original registry policy; incompatible
current bindings cannot silently reinterpret new operations.

Pure tests compare 0/2/3 precision and seeded large amounts to a Fraction oracle.
Native tests cover original tax/recognition, partial gain/loss, full AR release,
current authority on history and retry, direct SQL, late rollback, deterministic
locking, native reports/period locks, RLS, migration and unrelated worker
dispatch. API and Studio tests cover strict exact inputs, real scoped HTTP
identity, same-command transport ambiguity and independent evidence validation.
Actual HTTPS/Studio and populated restore acceptance belong to the integrated
fixed-source packet; passing component tests does not imply that final gate.

## Additive closing valuation and exact inverse, migration0131

The original five-table owner and private native posting participant also own
`revalue` and `reverse_revaluation` plan-v2 operations. A closing-rate observation
values only the outstanding foreign monetary AR; independent SQL NUMERIC
recomputes original cumulative release, foreign residual, closing conversion
and unrealized difference. Its separate Income/Expense account roles cannot
reuse revenue, realized FX, cash or tax roles. Original source, tax, registry,
foreign native AR and allocations remain immutable.

Only one posted closing valuation can remain active. A later receipt or valuation
requires an explicit three-human complete inverse, with current persisted
`finance_core.reverse` in addition to phase permissions. Its Generated native
entry and effect bind the exact original posting identity and inverse lines,
policy, scope and dimensions. This conservative boundary keeps existing
historical settlement arithmetic unchanged; it does not claim automatic close
reversal scheduling or settlement directly against a revalued basis.

Migration0131 creates a forward replacement of the accepted `fx_close` body
using explicit single-occurrence transformation guards. Original source/tax,
native snapshot/account, command, audit/outbox and SoD clauses are retained.
No existing migration text, RLS policy, ordinary-owner trigger or permission
cache is replaced. Its additive equation helper runs only for retained FX1
operations. Empty valuation history can roll back to the accepted original
owner while preserving original posted invoices; any retained valuation or
inverse refuses destructive rollback. Full acceptance of this extension is
pending its new native tests and actual five-stage HTTPS/populated restore.
