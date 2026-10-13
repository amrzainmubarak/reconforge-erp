# Original manufacturing supply plan

This experimental native PostgreSQL owner connects an actual approved BOM and
routing to current stock, sourcing, independently posted receipts, supplier AP,
budget consumption and existing ME1/ME2 production. It does not recreate inventory,
AP, FIFO, budgeting or GL. Community SQLite remains available through its existing
paths; this additional native owner returns backend unavailable there.

1. Select current tenant/workspace/organization/entity authority and an open period.
   Approve the actual BOM, effective routing/workcenter and matching budget first.
2. Prepare the original output demand and one positive exact minor-unit price
   ceiling for every BOM component. Creation retains demand without fabricating
   a stock movement, procurement obligation or posting.
3. An independent human approves the immutable original digest. Under common
   physical/FIFO pool locks, on-hand custody is limited by actual physical stock,
   existing native reservations and free original valued FIFO. The retained
   coverage shows gross, observed stock/reservations/FIFO, exclusive on-hand and
   exact net shortage separately for each UOM.
4. Create native `SRC5-MSP-` requisitions only for remaining unclaimed shortage.
   Open RFQ, retain original quotations, independently review deterministic
   selection, then publish the third-human native budget-backed award. Submit and
   independently approve the actual BPC purchase before receiving.
5. Prepare exact partial receipt quantities by original native purchase line,
   independently review, then post through a third human. Each actual committed
   receipt acquires exactly one quantity guard for its original requirement.
   Keep receipt dates forward in the native FIFO chronology; do not reinterpret
   earlier receipts or change their metadata to make a later command succeed.
6. Match supplier invoice quantities only against received lines. Independently
   approve the invoice, prepare AP, independently review it, then publish AP and
   consume the budget atomically through the native commitment owner. Preserve
   the original order and budget versions for retries.
7. Handoff accepts original posted Expense source claims and an explicit actual
   production date, at or after planning and all acquired receipts. The original
   planning request/digest remains immutable. All original gross quantities must
   be fully covered and every awarded shortage must have received/AP/budget
   closure. Native ME1 row creation transfers stock custody before ordinary ME1
   reservations; any later ME2 cost-admission failure rolls the entire transfer
   and native row creation back.
8. Continue the existing ME2 prepare/review/post material and expense cycle.
   Production stays in WIP quality hold until independently reviewed inspection
   posts accepted FG and abnormal loss. The linked original supply source remains
   verifiable after native production completes.

The Studio surface has Arabic/English labels, original gross/onhand/shortage UOM
rows, typed sourcing/receiving/AP forms, original source/quote hashes and a link to
ME2 WIP/QC. Client financial values remain exact decimal or minor-unit text. A lost
reply retains one immutable prepared command and prohibits a new command until
the same human retries it or receives a definitive rejection. After an ACK,
refresh original evidence before further mutations.

`approve`, `cancel`, `handoff` and every source/receipt/AP command validate current
persisted human, scope grants and native permissions. Cancellation retains
original demand/history and can release only unhanded stock after all unawarded
requisitions are explicitly cancelled. Awarded procurement is retained; no silent
reversal or abandoned commitment is created.

The bounded synthetic oracle is BOM10: ITEM2EA/MATERIAL3KG; starting1EA1200 and
0.500KG50; shortage1EA/2.500KG1450; material2700 + labor600 + overhead300 = 3600;
accepted9FG3240 + rejected1/360 + WIP0. Original native gate packets under
`output/msp-native-development-*` distinguish each source and preserve failures.
The original `complete-cycle-v2` packet has one passing mandatory native case and
zero skips/xfails/xpasses; before/after source digest is
`9c4b1db9a90109066d2d591d219d886fb5ebda6305eaf185ef7590b14ef4a703`.
Its original native handoff, final ME2 production and complete purchase snapshots
are retained under that packet's `actual-fixtures/`. The committed synthetic
Studio fixture pins original source digest
`83168181ab5117bd761d25e3b9a861d9d63b8f32ec095a7eb281d35620b1785d`.
Final integrated acceptance, ordered migration/restore and socket/TLS browser
verification remain separate root-owned gates. Unit/native gate durations are
verification evidence, not throughput benchmarks.
