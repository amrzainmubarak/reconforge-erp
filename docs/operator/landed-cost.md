# Paid landed-cost receiving and cancellation

Use **Partial procurement** (`/procurement-partial`) in Studio against the configured PostgreSQL server. Install the complete migration chain through `0125_pg_landed_cost_cancellation`, including the original `0121_pg_landed_cost` owner and `0123_pg_native_event_dispatch`. This experimental contract allocates already paid freight and duties before initial receiving. It uses the existing procurement, FIFO, AP, cash and GL engines.

Select the authorized tenant, workspace, organization and legal entity. Configure an active functional-currency supplier, untracked stock items with their actual unit precision, receiving locations, FIFO valuation policies, an open fiscal period, journal, AP and cash accounts. Selected lines must share the same receipt-clearing account. Create and submit a multiline purchase order, then have an independent authorized human approve it. See [multiline purchasing](../operators/procurement-multiline.md) for that prerequisite and subsequent partial invoices and payments.

The session must have current persisted scope and amount authority. The amount check includes the purchase total plus the bundle's paid charges. All mutations and retries require recent privileged-access confirmation. Read access requires `payables.read`, `inventory.read` and `finance_core.read`; the following permissions are additional:

| Operation | Required permissions | Human separation |
| --- | --- | --- |
| Prepare | `payables.manage`, `payables.settle`, `inventory.manage`, `inventory.valuation.manage`, `finance_core.manage` | Retains the preparer's canonical user ID |
| Review | `payables.approve`, `payables.settle`, `inventory.post`, `inventory.valuation.approve`, `finance_core.validate` | Reviewer differs from preparer |
| Receive and post charges | `payables.manage`, `payables.settle`, `inventory.post`, `inventory.valuation.approve`, `finance_core.post` | Third human differs from preparer and reviewer |
| Cancel before receiving | Same permissions as review | Human differs from preparer and any retained reviewer |

Open the approved order and enter a nonempty **Review or posting reason**. In **Paid landed cost receiving**, enter the bundle number, paid freight and duties as exact minor-unit integers, posting date, fiscal period, and each selected line's receiving quantity. At least one charge must be positive. Select **Prepare landed cost bundle**. Preparation reserves quantities and retains native receiving plans and a cash-entry draft; it does not publish stock or cash. Inspect each allocation and its preparer before another human selects **Review bundle**. A third human selects **Receive bundle and post paid charges**. Every selected inventory receipt, FIFO layer, inventory/clearing entry, native AP goods receipt and clearing/cash entry commits atomically.

For the synthetic two-unit example, receive `10 EA` at `1200` minor units per EA and `2.50 KG` at `2000` minor units per KG, with freight `777` and duties `224`. Merchandise values determine the allocation; quantities of different units remain separate:

| Line | Merchandise | Freight | Duties | Initial FIFO cost |
| --- | ---: | ---: | ---: | ---: |
| `10 EA`, `MAIN/STOCK` | 12000 | 548 | 158 | 12706 |
| `2.50 KG`, `NORTH/STOCK` | 5000 | 229 | 66 | 5295 |
| Monetary totals | 17000 | 777 | 224 | 18001 |

Freight and duties are allocated independently using integer largest remainders, with stable source IDs breaking ties. Zero allocated charges on an individual line are valid. Stock publication debits inventory by `18001`; the paid-charge entry debits clearing and credits cash by `1001`. Original native merchandise receiving and supplier invoice matching remain `17000`. Subsequent merchandise accruals clear that `17000` into AP; reviewed AP payments settle it separately. The example's combined cash outflow after full merchandise settlement is `18001`.

To reject an unreceived **Prepared** or **Reviewed** bundle, inspect it as the independent authorized human and select **Cancel unreceived bundle**. A reviewed bundle requires a third human for cancellation. Confirm **Cancelled; receiving reservations released** and the cancellation actor, reason and audit reference. Reload the purchase order and verify each affected line's reserved quantity. Cancellation releases only this bundle's quantities, including lines with zero allocated charges. Native drafts, reviews, receipt identities, source numbers, allocation history and command acknowledgements remain retained and consume their existing evidence budgets. Neither stock nor cash is reversed because neither was published.

For a replacement, reload the current order first. Enter a fresh bundle number and fill **all** fields again, including quantities, freight, duties, actual date and fiscal period; refreshing the order can remount and reset the form. The new preparation uses the current order `row_version`, a new command ID and fresh native receiving identities. An old cancelled bundle cannot progress through its receipt plans or generic cash posting. A posted bundle cannot be cancelled or rewritten; a complete posted reversal/return contract is a separate capability.

API clients use the same authenticated session, recent step-up, canonical scope headers (`X-ReconForge-Tenant`, `X-ReconForge-Workspace`, `X-ReconForge-Organization`, `X-ReconForge-Legal-Entity`) and mutation CSRF header (`X-ReconForge-CSRF`) as Studio. Read the current order and its actual line IDs first. For example, the preparation body for `POST /api/v1/landed-cost/plans` is:

```json
{
  "command_id": "operator-paid-cost-prepare-001",
  "number": "PAID-COST-001",
  "order_id": "CURRENT_ORDER_ID",
  "expected_version": 5,
  "lines": [
    { "line_id": "CURRENT_EA_LINE_ID", "quantity": "10" },
    { "line_id": "CURRENT_KG_LINE_ID", "quantity": "2.50" }
  ],
  "freight_minor": "777",
  "duty_minor": "224",
  "posting_date": "2026-10-12",
  "period_id": "CURRENT_OPEN_PERIOD_ID",
  "reason": "Paid carrier and duty evidence verified"
}
```

Replace the example IDs, version and dates with current configured values. Amounts and quantities are strings in the API; `expected_version` is an integer. `GET /api/v1/landed-cost/orders/{order_id}` returns four bundles per keyset page; pass its `next_after` as `after` for the next page. `GET /api/v1/landed-cost/plans/{id}` returns current evidence. For `POST /api/v1/landed-cost/plans/{id}/review`, `/post` or `/cancel`, send `command_id`, the current immutable `expected_plan_digest` and a nonempty `reason`. Each operation needs its own command ID. The current cancelled response retains its original phase `0` or `1`; use `status` and `cancellation` to recognize the terminal release.

If the acknowledgement is lost, keep the exact request, command ID, expected version/digest and original human identity. Use **Retry the same command**; the server repeats current authorization and returns the original exact acknowledgement after verifying retained source closure. Creating a replacement key while the result is unknown risks requesting a second business operation. An old prepare/review acknowledgement can describe its historical phase after cancellation; the current read supplies terminal evidence, and Studio preserves already observed terminal evidence against delayed acknowledgements.

| Symptom | Diagnosis and action |
| --- | --- |
| No POST appears; a receiving-quantity or positive-charge message is shown | Local input is incomplete. Fill quantities and a positive combined charge. Required HTML fields, including number/date/period, must also be valid. No command has been sent. |
| Unconfirmed response and retained command shown | Network, server failure or invalid acknowledgement. Retry the same command unchanged while current authority remains valid. |
| Version, phase, number or command conflict | Reload current evidence. Use fresh replacement fields and a new number/command only after the earlier result is known. |
| Authorization or duties refusal | Reconfirm privileged access and use a currently authorized independent human in the correct scope. Historical identity records do not grant current authority. |
| Cancelled bundle still appears among native plans | Expected retained evidence. Check its cancellation reference and released per-line reservation rather than deleting drafts. |
| Receipt chronology refusal | Use the actual business date. The shared FIFO chronology and immutable movement ordering remain authoritative; do not change a date merely to force acceptance. |

Supported bounds are 1–128 distinct selected lines per bundle, 200 retained bundles per order, and the multiline owner's 1024 retained receipts and 1024 invoices per order. Each selected line creates a receipt, so the native receipt budget may be reached before the bundle budget. Cancellation does not reclaim these counts. Numbers support 40 characters, command IDs 140, reasons 500; quantities must fit the item's precision, at most six decimal places, and yield exact merchandise minor units. Freight and duties are nonnegative with combined total `1..9000000000000000000`; each capitalized receipt cost must also fit that native minor-unit bound. Four returned bundles project at most 512 allocations. The contract uses functional currency, zero-tax merchandise and one shared clearing mapping; it does not add FX, supplier freight AP, tax returns, retroactive FIFO revaluation or supplier returns.

Before migration, verify a pre-upgrade PostgreSQL backup in an isolated restore target. Downgrading `0125` to `0124` is permitted only when cancellation storage is empty; any retained cancellation refuses that downgrade. Earlier landed-cost or procurement downgrades have their own populated-history guards. Preserve history with a forward correction, or restore a verified pre-upgrade backup when an earlier database state is required. A populated restore must retain cancellation records together with native receipts, drafts/reviews, stock/FIFO, AP/cash/GL, audit, outbox and command evidence. Verify the actual migration head and independent financial/quantity snapshots after restore. The reproducible native acceptance files are `tests/test_postgres_landed_cost.py`, `tests/test_postgres_landed_cost_api.py` and `tests/test_postgres_landed_cost_cancellation.py`; the real Studio and populated-restore journey is `apps/web/live/erp-landed-cost.spec.ts`. These are bounded acceptance surfaces, not production capacity or certification claims.
