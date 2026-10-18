# Partial customer invoice collections

This experimental PostgreSQL workflow collects an already recognized native stock-sale invoice in exact installments. It uses the existing receivables and Finance Posting engines. Each posted installment owns one native receipt, one allocation to its invoice, and one cash journal effect in the same transaction. The original FIFO consumption, COGS and revenue remain under their original owners.

The source must be a positive, zero-tax invoice in `Approved` or `PartiallyPaid`, with a positive residual and a completed stock-sale owner in `Invoiced`. A legacy full-collection plan and these installment plans cannot own the same invoice. Settlement appears on the native invoice as `PartiallyPaid` or `Paid`; the stock delivery remains `Invoiced`. Functional-currency collection is supported. Refunds, returns, allocation reversal, FX settlement and execution of external bank transfers are outside this workflow.

## Scope and current authority

Select the exact tenant, workspace, organization and legal entity. API execution binds this scope from the authenticated request; the preparation body cannot substitute another scope. Database isolation remains `FORCE ROW LEVEL SECURITY`, and the native transaction uses `READ COMMITTED` with invoice and plan locks.

For browser API requests, use the existing authenticated same-origin session and scope headers `X-ReconForge-Tenant`, `X-ReconForge-Workspace`, `X-ReconForge-Organization` and `X-ReconForge-Legal-Entity`. Mutations also require `X-ReconForge-CSRF`. Session setup and step-up follow the [browser administration session runbook](../operations/browser-administration-sessions.md).

| Action | Required collection-route permissions | Actor separation |
| --- | --- | --- |
| Read a plan | `finance_core.read`, `receivables.read` | Current authorized reader |
| Prepare | `finance_core.manage`, `sales.manage`, `receivables.manage` | Currently authorized human maker |
| Review | `finance_core.validate`, `sales.approve`, `receivables.manage` | Human other than the maker |
| Post | `finance_core.post`, `sales.manage`, `receivables.manage` | Third human, other than maker and reviewer |
| Cancel unposted | `finance_core.validate`, `sales.approve`, `receivables.manage` | Human other than maker and any retained reviewer |

These are the collection action permissions; navigating the stock-sales workspace requires its existing read permissions as well. Mutations require current human identity and step-up authority. Admission repeats persisted permissions and applicable amount policy, including on a command retry: a retained command does not preserve revoked authority. Amount policy uses the original invoice currency precision.

## Studio operation

1. In Stock sales (`/stock-sales`), select the invoiced delivery tranche and open **Collect this invoice in installments** / **تحصيل هذه الفاتورة على دفعات**. Check the displayed outstanding minor units and original invoice evidence.
2. Enter the installment as positive integer minor units, a unique receipt number, collection date, open period, cash journal, cash asset account and reason. The cash account must differ from the original receivable account. Studio retains that original receivable mapping.
3. Choose **Prepare invoice installment** / **إعداد دفعة الفاتورة**. Preparation freezes the current invoice version, collected amount, currency policy and exact native draft. It creates no cash receipt or published cash effect.
4. A different authorized human checks the frozen amount and evidence, enters a reason, and chooses **Review invoice installment** / **مراجعة دفعة الفاتورة**. This validates the retained native entry.
5. A third authorized human chooses **Post invoice installment** / **ترحيل دفعة الفاتورة**. Confirm the returned native receipt and cash effect identifiers, then reload the invoice residual. Posting debits cash and credits the original AR account for exactly the installment amount. Receipt, allocation, journal effect, invoice state, immutable command acknowledgement, audit and outbox commit together; failure rolls back the entire transaction.

One Prepared or Reviewed installment can claim an invoice at a time. After posting, prepare the next installment against the refreshed invoice. A changed source version, changed allocation or incompatible period/account/currency policy refuses continuation; reload and resolve the source conflict before submitting another request.

## API packets and retained acknowledgements

All routes are under `/api/v1/commercial-collections`. Preparation is `POST /plans`. The following example uses placeholders for actual native identifiers; `"10000"` means 10,000 minor units under the invoice's retained currency precision.

```json
{
  "command_id": "collection-invoice-01-prepare",
  "source_kind": "ARReceipt",
  "source_id": "<native-invoice-id>",
  "amount_minor": "10000",
  "journal_code": "<cash-journal-code>",
  "period_id": "<open-period-id>",
  "posting_date": "2026-10-10",
  "debit_account_code": "<cash-asset-account-code>",
  "credit_account_code": "<original-invoice-AR-account-code>",
  "reason": "Partial customer collection",
  "receipt_number": "RECEIPT-001"
}
```

Review, post and cancellation use `POST /plans/{plan_id}/review`, `/post` and `/cancel`, respectively, with this strict body:

```json
{
  "command_id": "<unique-command-id-for-this-action>",
  "expected_plan_digest": "<retained-64-lowercase-hex-plan-digest>",
  "reason": "<reason-for-this-action>"
}
```

Responses contain `{"plan": ...}`. Use `GET /plans/{plan_id}` for the current projection. The lifecycle is `Prepared` phase 0, `Reviewed` phase 1, `Posted` phase 2, or terminal `Cancelled` phase 3. Retain the plan identifier, digest, exact request, command identifier, actor and scope for each action.

If the response is lost, retry the same action with the same actor, command identifier, exact body and scope. Studio exposes **Retry retained collection command** / **إعادة أمر التحصيل المحفوظ** and retains that packet while the outcome is uncertain. Do not issue a new command identifier to discover whether the first command committed. A successful replay returns the original immutable acknowledgement; a changed actor or body using that command identifier is refused. Preparation and review acknowledgements retain their historical phases even after posting or cancellation. Read the current plan before choosing a subsequent action. Current permission revocation can refuse a replay even when the earlier command committed.

## Unposted cancellation and replacement

A Prepared or Reviewed installment can be cancelled by the independent actor in the table above. For a Reviewed plan this requires a third human distinct from its maker and reviewer. In Studio, provide the cancellation reason and choose **Cancel unposted invoice installment** / **إلغاء دفعة الفاتورة غير المرحّلة**. API cancellation uses the retained plan digest and a new cancellation command identifier.

Cancellation releases the pending invoice-residual claim and the prepared receipt-name claim. It retains the exact original payload, the native Draft or Validated entry, any independent review, historical command acknowledgements, and immutable cancellation audit/outbox evidence. The terminal projection includes `cancelled_actor_id` and `cancellation_reason`; `receipt_id` and `posting_effect_id` remain null. It produces no receipt, allocation or published cash effect. A cancelled plan cannot be reviewed or posted. A posted plan cannot be cancelled by this operation.

Reload the current invoice and prepare a replacement with a fresh command identifier. The cancelled plan's receipt number is reusable only if no retained native receipt or native idempotency reservation already owns it. Preparation refuses visible receipt conflicts but does not reserve the native receipt namespace until posting. A competing native command or an RLS-hidden claim can therefore block a prepared plan later. Resolve this with authorized cancellation and a valid replacement number; do not edit namespace claims or financial records directly.

## Bounds and incident checks

- Each installment is between 1 and 9,000,000,000,000,000,000 minor units and cannot exceed the current exact invoice residual. Supply canonical decimal integer text, with no decimal point or exponent. Currency precision, rounding policy and registry identity must equal the original invoice policy.
- An invoice admits at most 200 retained installment plans, including cancelled plans, with one active plan. Cancellation releases a pending claim but does not reset this evidence budget.
- Receipt numbers use at most 64 ASCII letters, digits, hyphen, underscore or dot, start with an alphanumeric character, and are retained uppercase. Command identifiers use at most 140 characters and reasons at most 500 characters. The period must be open and the posting date cannot precede the invoice date.

For an unexpected refusal, retain the command, plan and native invoice identifiers and inspect the current scoped invoice allocations, plan phase, original journal and audit evidence. Do not patch a plan phase, native draft, receipt allocation or cash effect through SQL. Deferred bidirectional owner checks run at the outer transaction boundary and refuse detached or modified source/effect/evidence writes, including direct SQL; roll back a failed transaction before continuing. Current SQL admission also checks persisted actor permissions and separation of duties. A cancellation/post race serializes on the plan and invoice locks and admits only a valid terminal outcome.

These are bounded workflow limits, not a throughput, production readiness or general sales-completeness claim. Reproduce native acceptance with the owned launcher and both complete owner test files:

```powershell
python .github/scripts/verify_commercial_collections.py tests/test_postgres_commercial_collections.py tests/test_postgres_commercial_collection_cancellation.py
```

## Upgrade, restore and rollback

Apply the repository's complete ordered Alembic chain through an appropriately scoped migration administrator. Collection cancellation migration `0124_pg_collection_cancellation` depends on `0123_pg_native_event_dispatch`. Do not broaden runtime grants to work around an owner-closure refusal. Back up the complete native database, including collection owners and commands, AR invoices/receipts/allocations, GL drafts/reviews/effects, identity policies, audit and outbox. Verify a populated isolated restore and financial/evidence fingerprints before using the restore as a recovery route.

Downgrading 0124 refuses any retained cancellation evidence or phase-3 plan. With no cancellation history, the guarded downgrade can restore the preceding collection protocol while preserving supported earlier collection history. The original collection-owner downgrade separately refuses retained collection history. Never delete evidence to make a downgrade pass.

For an application rollback, preserve the additive database schema and use a reader/writer compatible with terminal `Cancelled` phase 3. Older readers may reject that representation, so verify compatibility before deploying them against populated data. If rollback requires a pre-upgrade schema, recover a verified isolated pre-upgrade backup and reconcile its recovery point explicitly; do not force a destructive downgrade over retained financial history. See the [commercial collection module contract](../modules/commercial-collections.yaml) and the existing [stock-sales runbook](stock-sales.md) for the owning source cycle.
