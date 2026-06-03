# Demo Scenarios

These scenarios explain the business meaning behind common ReconForge exceptions. They are written for finance, audit, ERP, inventory, and workshop teams reviewing local ERP exports.

## 10-Minute Demo Flow

Run:

```bash
reconforge demo run --output output/demo
```

Then open:

- `output/demo/dashboard.html`
- `output/demo/executive_report.html`
- `output/demo/management_pack.xlsx`
- `output/demo/evidence/index.html`
- `output/demo/review_register.xlsx`
- `output/demo/client_pack/summary.md`

Start Studio to update review state:

```bash
reconforge studio --input examples/sample_data --output output/demo
```

The demo uses sample data and creates local artifacts only.

## 1. Stock Movement Without GL Posting

- Business meaning: Inventory was issued, consumed, received, or adjusted, but ReconForge did not find a matching accounting line.
- Why it matters: Inventory value, expense, WIP, or variance accounts may be incomplete at period close.
- Expected ReconForge output: `stock_without_gl` exception in stock-to-GL results and management pack.
- Suggested reviewer action: Confirm posting date, source document, account mapping, and whether the GL posting is delayed or missing.

## 2. GL Posting Without Stock Movement

- Business meaning: Accounting has an inventory, WIP, expense, or variance line without matching stock movement evidence.
- Why it matters: The GL may contain manual postings, timing differences, or unsupported adjustments.
- Expected ReconForge output: `gl_without_stock` exception.
- Suggested reviewer action: Trace journal reference, source document, cost center, and supporting approval.

## 3. WIP Older Than 90 Days

- Business meaning: A work order remains open or costed after more than 90 days.
- Why it matters: Old WIP can indicate stalled jobs, billing gaps, provisioning needs, or operational leakage.
- Expected ReconForge output: WIP aging row in the `90+` bucket.
- Suggested reviewer action: Assign an owner to close, bill, provision, or explain the work order.

## 4. Direct Purchase Fitting Risk

- Business meaning: A purchase was linked directly to a work order instead of flowing through normal stores controls.
- Why it matters: Direct fit can be legitimate, but it needs evidence of receipt, issue, approval, and customer/job linkage.
- Expected ReconForge output: `direct_purchase_fitting_risk`.
- Suggested reviewer action: Attach PO, receipt, work-order approval, and invoice evidence or escalate missing documentation.

## 5. Old Part Not Returned

- Business meaning: A controlled part category was issued, but the old or replaced part was not returned.
- Why it matters: Missing returns can indicate stores leakage, warranty evidence gaps, or incomplete workshop controls.
- Expected ReconForge output: `old_part_return_missing`.
- Suggested reviewer action: Confirm whether the old part was returned, scrapped, retained by customer, or not required.

## 6. High-Value Variance

- Business meaning: Matched stock and GL records differ above tolerance or a high-value transaction requires review.
- Why it matters: Large value differences can affect inventory valuation, expense recognition, or audit sampling.
- Expected ReconForge output: amount variance or high-risk exception with risk score and amount fields.
- Suggested reviewer action: Review source valuation, exchange rate, quantity, account, and posting-date assumptions.

## 7. Cancelled PO With Later Cost

- Business meaning: A cancelled purchase order is still linked to later stock movement or work-order cost.
- Why it matters: Cancelled procurement documents should not usually support later operational cost without explanation.
- Expected ReconForge output: cancelled PO linkage exception in work-order controls.
- Suggested reviewer action: Check PO status history, replacement PO, goods receipt, and approval trail.

## 8. Accepted Risk Example

- Business meaning: The reviewer agrees the exception is real but acceptable for a documented reason.
- Why it matters: Accepted risk should not disappear from the register; it should carry rationale and ownership.
- Expected ReconForge output: Review status `Accepted Risk` with `accepted_risk_reason`.
- Suggested reviewer action: Document the business reason, responsible owner, review date, and next review trigger.

## 9. Escalated Exception Example

- Business meaning: The exception cannot be resolved by the initial reviewer.
- Why it matters: Escalation keeps unresolved finance, audit, ERP, or operations issues visible.
- Expected ReconForge output: Review status `Escalated` with `escalation_owner`.
- Suggested reviewer action: Assign an owner, add a note, and agree a response date.

## 10. Resolved Exception Example

- Business meaning: The issue was corrected, explained, or matched after additional evidence.
- Why it matters: Resolved exceptions show control follow-through and support audit evidence.
- Expected ReconForge output: Review status `Resolved` with reviewer note and decision reason.
- Suggested reviewer action: Keep the supporting source record, correction reference, or explanation in the evidence pack.
