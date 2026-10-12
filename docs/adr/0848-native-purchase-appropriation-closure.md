# 0848 — Native purchase appropriation closure

Status: accepted engineering decision for an experimental PostgreSQL slice.
Date: 2026-10-10.

Existing budgets conserve independently recorded Reserve, Consume and Release events. Existing multiline procurement conserves native quantities, FIFO receipt values and supplier AP effects. A purchase can otherwise be approved without a binding approved appropriation, and AP publication can occur independently of an obligation's budget consumption.

The `BPC1-` purchase number namespace identifies native multiline purchases whose entire original merchandise obligation is reserved at creation against one approved native budget. A retained owner seals the native order, approved scope, currency policy and native Reserve event. The original source stays in the existing procurement, inventory, AP and financial engines.

Only the appropriation owner publishes a reviewed AP invoice. Native Consume and the existing OPS1 AP effect commit together. Deferred SQL closure requires equal accrued AP and consumed obligation totals, exact original source prices and quantities, complete native commands and evidence, and one consumption per invoice. Calling an existing budget command or detached procurement publication cannot commit only half of the operation.

Independent terminal Release returns the exact unreceived remainder when every received per-line quantity has been accrued, every retained source draft is complete, and no prior release exists. Release preserves the original purchase version and source history, and prohibits subsequent procurement progression. Existing AP installments may settle already accrued obligations after release without changing the released source version.

Acquire the original open fiscal period before the native budget envelope, then the purchase parent, native AP and financial objects. AP consumption uses the original appropriation period; it never acquires a second period after the envelope. Receipt preparation locks the purchase and reads appropriation closure without acquiring an envelope lock. A forced PostgreSQL blocking test proves release/receipt serialization.

New source routing tests the retained namespace before querying protected appropriation tables. Ordinary purchase roles retain their previous read and receipt capability with SELECT revoked on the new tables; identified BPC1 sources fail closed. Current persisted permissions, scope grants, amount policy and privileged-session assurance are repeated before returning a retained command receipt.

Amount authorization derives the original obligation from the approved envelope's retained precision. Native owned reads, pages, actions, cached-command retries and SQL closure reject a live currency precision that differs from that policy. Normal bound-currency SQL updates already refuse drift; the additional owner guard also detects a damaged administrator-restored catalog without reinterpreting historical amounts.

Paid landed-cost receiving is excluded from BPC1 until charges have their own appropriation contract. Merchandise budgets cannot silently fund a paid cash charge. Native receipt capitalization must equal original merchandise value in this slice. Supplier return and budget reinstatement are a separate source inverse contract.

The initial ceiling remains 128 original lines, 1024 receipts/invoices under the existing procurement limits, and 1000 total native commitment events per approved envelope. This is a bounded contract; it establishes no 1000-line sales/purchasing or global performance claim.

Empty rollback restores the prior procurement verifier and removes only empty appropriation tables. Recreated tables require the deployment role bootstrap to restore their previous app ACL. Populated history refuses downgrade and requires forward correction or verified pre-upgrade restore. The browser restore membership includes the native envelope, native budget commands/events and the new owner commands/plans.

Acceptance requires the native, authenticated API and actual HTTPS Studio cycles; direct SQL refusal, current-authority retries, fault rollback, concurrent single outcomes, independent integer/GL oracles, empty/populated migration tests and populated restore remain mandatory. Development evidence is distinguished from final clean-commit acceptance.
