# Foreign receivables, retained tax and realized FX

The experimental PostgreSQL surface is `/operational-fx-tax` in Studio and
`/api/v1/operational-fx-tax` in the normal API. Enable the existing scoped native
Finance Core backend. Use synthetic data for the acceptance walkthrough; this
slice neither obtains live exchange rates nor supplies tax law.

## Configure and operate

Prepare active foreign and functional currency masters with the correct
registry precision, a customer in the foreign currency, its credit limit,
an open scoped fiscal period and a journal in the entity's functional currency.
Select five distinct native accounts: AR Asset, Cash Asset, Revenue Income,
Realized Gain Income and Realized Loss Expense. Tax components use Liability
accounts outside those five roles; multiple components may share a tax account.

Sign in with the normal local human identity, perform recent reauthentication
and apply authorized workspace/organization/entity IDs. Enter source invoice
number, customer code, foreign net minor units, posting/due dates, native period
and journal, country/transaction class, original exact decimal spot rate,
explicit UTC observation and source. Add up to eight ordered net-exclusive tax
components with policy ID/version, fraction, effective dates, source and native
liability account. The retained country/class must match every component and
the posting date must fall within every component's effective period.

Prepare as human one. Inspect original rate/tax, foreign gross and functional
journal. Human two signs in separately and reviews the retained digest and
reason; native customer credit controls apply without an implicit override.
Human three independently posts. Original native AR becomes Approved and
functional AR/revenue/tax are posted by the existing ledger owner.

Select the retained invoice to prepare a partial receipt. Enter foreign minor
units, a nonregressing accounting date, open period, reviewed settlement rate,
explicit UTC observation/source and reason. Review and post with separate
humans. Posting closes the native foreign allocation and functional cash,
historical AR release and realized gain/loss atomically. No bank transfer is
instructed. Complete the pending plan before preparing another installment;
the history is bounded at 200 operations after recognition, including any
closing valuations and their inverses.

### Closing valuation and explicit inverse

For an outstanding posted source with no pending operation, choose **Prepare
closing valuation**. Enter its nonregressing date/open period, exact closing
rate, UTC observation/source and two additional distinct native accounts:
Unrealized Gain Income and Unrealized Loss Expense, outside the original five
roles and tax accounts. The proposed difference is the closing conversion of
the foreign outstanding balance minus the original functional outstanding
balance. Three separate humans review/post its retained native journal. Native
foreign AR, receipts, original revenue and taxes remain unchanged.

For the example below, after the first receipt, `7401` foreign minor units
remain with original functional AR `9251`. A closing rate `1.35` values that
monetary balance at `9991` and posts AR debit/unrealized gain credit `740`.
The register displays both original and closing carrying values. Before a
receipt or another valuation, choose **Prepare exact valuation reversal**;
enter date/open period/reason and review/post with three humans, each also
holding current `finance_core.reverse`. Its Generated native posting must
exactly invert the original valuation effect, retained policy and dimensions.
AR returns to `9251`, unrealized gain to zero, and ordinary partial settlement
can then resume with the original cumulative historical-release equation.
Zero-difference valuations and inverse-of-inverse proposals are refused.

## Exact example and oracle

For EUR source precision 2 and USD functional precision 2, enter net `10001`,
synthetic tax fraction `0.14` and original spot `1.25`. The foreign tax is `1400`
and gross `11401`. Functional revenue is `12501`, tax `1750` and AR `14251`.
Collect `4000` at `1.3`: cash `5200`, original-rate AR release `5000`, gain `200`.
Collect the remaining `7401` at `1.2`: cash `8881`, AR release `9251`, loss `370`.
Both native foreign AR and functional AR then have exactly zero residual.

The independent oracle uses rational arithmetic: positive half-up rounding of
`n/d` is `floor((2*n+d)/(2*d))`. Currency conversion multiplies a foreign minor
amount by the exact rate and `10^(functional_precision-foreign_precision)`.
Historical release for a tranche is the converted cumulative foreign paid
amount minus the previously released original-rate balance. Functional tax
components are differences between successive converted net-plus-tax prefixes.
Do not sum independently rounded tax or original-rate installment conversions.

Input/output money uses canonical integer minor-unit strings. Currency precision
is retained separately; JPY precision 0 and KWD precision 3 are supported by
the native precision/oracle cases. Binary floating point, decimal minor-unit
strings, missing policy data and rates with exponents are refused. A tranche
that converts to zero functional cash is refused rather than producing a silent
zero posting. Amounts and complete debit turnover must fit the declared
9,000,000,000,000,000,000 minor-unit ceiling.

## API, retries and current authority

Use the normal browser cookie/session, CSRF token for mutations and
`X-ReconForge-Workspace`, `X-ReconForge-Organization`,
`X-ReconForge-Legal-Entity` headers. Strict schemas reject unknown fields.

| Relative request | Purpose |
| --- | --- |
| `POST /invoices` | Prepare recognition with source fields above and a new `command_id`. |
| `GET /invoices?after=...&limit=25` | Authorized keyset source register, follow `next_after`. |
| `GET /invoices/{source_id}` | Original source, foreign/functional residual and bounded exact history. |
| `POST /invoices/{source_id}/settlements` | Prepare a retained installment with `foreign_minor`, `settlement_rate`, period/date/reason and new command. |
| `POST /invoices/{source_id}/revaluations` | Prepare closing rate/observation, unrealized gain/loss accounts, period/date/reason and new command. |
| `POST /invoices/{source_id}/revaluation-reversals` | Prepare exact `original_revaluation_id` inverse with period/date/reason and new command; requires current reversal permission. |
| `POST /plans/{plan_id}/review` | Second human, command ID, `expected_plan_digest`, reason. |
| `POST /plans/{plan_id}/post` | Third human, independent command ID, retained digest, reason. |
| `GET /plans/{plan_id}/evidence` | Native closure and exact source/plan/ledger proof. |

Prepare requires `finance_core.manage` and `receivables.manage`; review requires
`finance_core.validate` and `receivables.approve`; post requires
`finance_core.post` and `receivables.manage`. Read requires `finance_core.read`
and `receivables.read`. Each reads/retries rechecks current grants, source gross
in both original precisions and the complete emitted journal's debit turnover.
A later permission revocation denies an old authorized command retry.

When a transport response is lost, malformed or uncertain, keep the exact
actor, path, body, command ID and digest. Studio locks editing and presents
**Retry the same command**. The historical acknowledgement is retained while
server detail can show a later phase; an old acknowledgement cannot overwrite
a newer phase already observed. Never create a new command merely because a
response was lost. Resolve a definitive state/digest conflict by inspecting
current retained evidence and preparing a corrected proposal explicitly.

## Evidence, reports and recovery

Select a retained plan and verify evidence. Studio independently hashes exact
`canonical_source_json`, `canonical_plan_json` and `canonical_snapshot_json`
against source, plan and native validation digests, checks exact balanced
BigInt totals, native effect identity and the three distinct human phases.
Download preserves the exact strings and audit/outbox references. SHA-256
content seals are not signatures. Do not parse large canonical numeric JSON
with a floating-point parser before hashing its bytes.

The existing native posted balances, independently reviewed financial
classification map and reports include these functional postings. Fully posted
history remains verifiable after a period closes; fresh financial effects
require the current open period. Account, currency, original rate, tax policy
and phase evidence cannot be edited to repair a posted result. Only the explicit
closing-valuation inverse can reverse that effect; generic journal reversal
cannot detach FX1 history. Original invoice/source reversal remains separate work.

Before upgrade, retain a verified backup and matching application/migration
source. Empty owner tables support additive rollback. A populated downgrade
refuses to discard evidence; use the governed populated restore procedure,
verify the five owner tables, original AR/allocations, native effects, retained
commands, audit/outbox and independent source equations on the restored DB,
and bind acceptance to that exact source/backup hash. Integrated HTTPS populated
restore evidence is required separately from component/native unit results.

No claim is made for tax-jurisdiction compliance, Production Ready status,
external settlement, AP FX, inclusive/compound tax or
foreign inventory sources. Benchmarks of retained snapshot reads are distinct
from complete native posting workloads; any performance claim requires matched
source, workload, host/durability settings and retained raw results.

The original FX1 owner has 19 unique accepted native cases and actual HTTPS
plus populated restore acceptance at integrated `02749705`; its raw report is
`output/wave4-fx-browser-027/report.json` (93.093 seconds, one expected case,
zero skipped/unexpected/flaky). The additive migration0131 closing valuation
and inverse extension requires its own complete native and actual five-stage
browser/restore gate; the earlier three-stage packet does not validate it.
