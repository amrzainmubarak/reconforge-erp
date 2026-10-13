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

The original SQL export is enabled with `RECONFORGE_MSP_NATIVE_PROOF_DIR` on the
bounded complete native test. `native-supply-original-populations.json` preserves
all original supply requirements and coverage, starting stock receipts and FIFO,
SRC quotations and award, BPC commitments and budget events, partial receipts and
AP, quantity guards/releases, ME1/ME2, quality inspection and the complete native
GL. The exporter uses the ordinary authenticated tenant role and records its
non-superuser/non-bypass status. Native `NUMERIC` columns retain exact PostgreSQL
decimal text; native `BIGINT` columns retain JSON integer tokens. Identities and
private fixture credentials are excluded.

Run `.github/scripts/verify_manufacturing_supply_cycle_oracle.py` with Python
`-I` and separately with `-I -O`, supplying `--proof`, its independently retained
`--proof-sha256`, and a new `--output` file. The file-only stdlib verifier derives
gross BOM scaling, original partial on-hand and net shortage, exact received
custody and handoff releases from originals. It admits the independent SRC and
ME2 stdlib scripts only by source digests captured with those original bytes.
SRC proves actual quotation/award/AP/budget equations. ME2 proves material FIFO,
original labor/overhead capacity, issue/WIP, quality hold, accepted FG and loss.
The ME2 projection excludes precisely the separately verified AP accrual effects;
its digest and excluded original effect IDs are reported, and the full original
AP/production native journal lines are checked again before the final GL totals.
An internal seal is reproducibility evidence; the externally supplied raw SHA
remains required and this tool does not claim external attestation.

For the real native browser gate, use
`seed_manufacturing_supply_browser`,
`manufacturing_supply_browser_configuration`, and
`verify_manufacturing_supply_browser` from `tests/manufacturing_supply_browser.py`.
The seed supplies only approved original engineering/budget/masters, two partial
stock inputs and the original posted labor/overhead expense inputs. It explicitly
requires zero planner, sourcing, purchase and production documents before the
browser starts. Pass configuration as `RECONFORGE_MANUFACTURING_SUPPLY_SOURCE`.
The required single spec/config are `apps/web/live/manufacturing-supply-cycles.spec.ts`
and `apps/web/live/manufacturing-supply.playwright.config.ts`. They perform actual
Studio/API demand and coverage, quotation and three-human award, two original
receipts and two AP/budget publications, atomic native handoff and existing ME2
issue/quality/FG. Lost-ACK probes reuse the exact original command bytes and human.
The helper supplies the protected-table union, sibling-workspace probes and three
restore tamper statements for original net quantity, Core guard release and the
retained terminal handoff command. The common TLS runner and CI registration are
root-owned; spec collection alone is not native browser or restore acceptance.

Every supply mutation also returns `manufacturing-supply-command-ack-v1` from
its exact immutable PostgreSQL command receipt inside the caller's business
transaction. The original command/operation/actor, source digest, historical
version and native owner/command links remain unchanged on replay. The API seals
the public projection of that stored response and provides the submitted typed
model separately. Studio validates both the original native request digest and
the normalized submitted body, exact subject/scope/current human, requested
operation/phase and native response membership before clearing a retained
command. An unqualified ACK retains the command and triggers no success refresh.
An authoritative later read may legitimately show progress beyond a historical
replayed ACK. Current denied reads remove displayed source and purchase evidence;
an unknown command remains retained for the same human's qualified retry.

Current amount authority covers the largest exposed original financial value,
including every retained plan unit-price ceiling and native supplier quotation
unit price, as well as transaction totals. These values use the plan's captured
monetary precision. Fractional demand does not reduce authority over an exposed
unit price: the supported original `0.001 KG × 3000 minor = 3 minor` requirement
still exposes a `30.00` unit price. A retained `5000` unit-price quote has a `5`
minor-unit total and exposes `50.00`. A lower current read cap refuses whole-source
reads, lists, child reads, command responses and immutable replay. A refused new
quote response rolls back its native offer, owner version and command together.
Current persisted permissions and hierarchy grants are checked again after a
blocked source lock; historical receipts never restore revoked authority.

The focused native regressions are in
`tests/test_postgres_manufacturing_supply_read_authority.py`. Original setup-error,
authorization-red and corrected packets are retained separately under
`output/msp-fractional-authority-native-*`; they are development verification.
The unsupported `0.001 × 3001` example is explicitly retained as an exact-minor
input rejection, and no rounding or procurement domain contract is changed.

Studio binds the original budget's full monetary policy after normalizing its
public projection: the budget envelope carries `currency_code` at envelope
level, while MSP captures it inside `monetary_policy`. All five captured values
(currency, precision, rounding policy, registry version and registry digest)
must match, along with the original budget ID and selected hierarchy. Valid
native budget evidence enables the shortage form; any altered binding or
current denied read keeps native sourcing disabled. The original approved
source/budget projection regression is in
`apps/web/src/components/ManufacturingSupplyPurchasing.test.tsx` and retains the
same raw original proof SHA as the supply oracle. The root-owned actual TLS
failure and the focused Studio red/green remain separate evidence packets.
