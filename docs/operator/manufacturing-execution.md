# Actual-material manufacturing execution (ME1)

Open **Manufacturing execution** in Studio at `/manufacturing-execution`, authenticate a human and confirm recent financial authority. Apply the exact workspace, organization and legal entity. PostgreSQL holds the operational source, actual FIFO layers, financial entries, current authority, audit and outbox in the same transaction. SQLite execution returns an explicit unsupported-backend response.

Prepare a versioned BOM with one finished item, a positive planned output quantity and up to 100 distinct component items. Each quantity uses the item's original base UOM and precision. A different authorized human approves the immutable exact version. A production order references that version, reserves the complete expanded material requirement and fixes the component/finished locations, original FIFO policies, native journal, WIP asset and abnormal-scrap expense accounts. Expansion must produce exact base-unit integers; fractional conversion is refused.

Prepare the whole component issue. The owner freezes original FIFO consumptions and an exact native inventory-credit/WIP-debit draft. A second human reviews this complete retained source; a third posts its native movement, valuation, consumption and GL effect atomically. Existing sales reservations and manufacturing claims share physical capacity and stock/FIFO locks. There is no negative stock concession.

Once WIP is posted, prepare a partial disposition with nonnegative good quantity and explicit abnormal material scrap quantity; their sum must be positive and within the original unprocessed quantity. An independently reviewed good output posts through the existing native inventory receipt engine with WIP as its offset. Abnormal material scrap posts an expense debit and WIP credit. Three distinct humans govern each disposition. The final disposition releases the exact residual cost, preserving `issued cost = finished cost + abnormal scrap expense + remaining WIP`. Abnormal waste is treated as expense in this bounded actual-material contract. This follows the treatment described in [IAS 2 inventories](https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/); the module makes no compliance certification claim.

An order can be cancelled only before material posting. Cancellation retains its original BOM, requirements, commands, review and financial draft, marks the native material claim terminal and releases reserved capacity. A prepared or reviewed output can be cancelled before native posting; its retained receipt plan/review remain source-owned and its scrap draft is voided. Complete or cancel the current output before preparing another. Posted material issues and output effects cannot be cancelled or independently reversed through public native engines.

If a response is lost, use **Retry retained command** in the same human session. The exact route, body, command ID and expected source digest remain fixed. Historical prepare/review acknowledgements stay verifiable even after later posting or cancellation. Every retry rechecks current permission, scope and retained source amount; an acknowledgement is not a permission exemption. A changed actor or payload conflicts with the original command. Do not invent a new command until the prior outcome has been resolved.

The public requirement record has immutable parent/BOM digests, nested canonical scope, native item/UOM identities and exact original quantity. Its read uses current full parent authority. It is material demand provenance, not a net shortage or an MRP calculation. Direct SQL cannot fabricate source phases, review events, requirement JSON, historical ACKs, native receipt effects or balanced-but-unowned manufacturing GL. The deferred native source closure must succeed at commit.

The independent synthetic cycle consumes `2 EA` from `10 EA / 12000 minor` and `3.000 KG` from `20.000 KG / 3333 minor`: HALF_EVEN actual FIFO cost is `2400 + 500 = 2900`. A first output of `3 good + 1 scrap` produces `870 good / 290 scrap`, and the final `6 good` releases `1740`. Final finished quantity/cost is `9 / 2610`, abnormal scrap `1 / 290`, WIP `0`; six original native effects balance at `21133` turnover. These are fixture expectations; each accepted runtime packet must bind its actual source, native populations, command and report hashes.

Limits are 100 components and 200 retained output attempts per order, with exact monetary or scaled quantity values bounded at `9000000000000000000`. Same-date finished receipts must obey existing native movement chronology. The owner deterministically tests at most **4096** source identities and retains `receipt_identity_candidates` in the original source. Exhaustion refuses the entire command with no cost, quantity or financial write; use a later valid business date. Search work can increase as the same-date pool grows. This slice has no high-volume manufacturing claim. A future native monotonic receipt sequence needs a versioned chronology contract, compatibility analysis and measured same-workload acceptance; raising this search ceiling is not that solution.

Required GL dimensions, alternative UOMs, lot/serial tracking, partial component issue, normal yield/standard costing, labor, overhead, routing, quality-control release, FX/tax and MRP remain unsupported. Their omission is an explicit scope boundary.

Migration `0133_pg_manufacturing_execution` adds immutable FORCE RLS owner tables and the native claim marker without rewriting previous migrations. Downgrade is permitted only with no retained manufacturing owner data. Populated downgrade refuses atomically, keeping the source, native column, function bodies and commands intact. Use a verified PostgreSQL backup/restore and the actual ordered migration gate before an operational upgrade or rollback; an empty catalog proof does not substitute for populated restore.
# Independent financial reproduction

The file-only verifier `.github/scripts/verify_manufacturing_cycle_oracle.py` uses
the Python standard library and independent integer/Fraction calculations. Run it
outside the checkout with `python -I` (and repeat with `-I -O`) over the original
`manufacturing-execution-proof-v1` JSON and the separately retained original raw
SHA-256:

```powershell
python -I .github/scripts/verify_manufacturing_cycle_oracle.py --proof original-proof.json --proof-sha256 ORIGINAL_64_HEX_SHA --output verified-proof.json
```

It verifies the original BOM/UOM demands, original receipt quantities and costs,
whole FIFO allocations and residuals, partial good and abnormal-scrap cost,
zero final WIP, exact native posting populations and snapshot seals, and retained
three-person source/effect identities. It does not authorize data writes, measure
manufacturing throughput, or supply an external attestation. The caller must retain
the original raw digest separately; hashing a replacement file is not sufficient.

The optional bounded driver `.github/scripts/benchmark_manufacturing_api.py` uses
the shared native HTTPS runtime. For each fresh synthetic tenant, it seeds the
masters and two original material receipt postings before timing. It then times
22 real API requests, including login/step-up, governed BOM and material issue,
reviewed output cancellation, two partial good/scrap dispositions and the final
native order read. Four manufacturing postings occur inside that business window;
the independent oracle verifies those four and the two original input postings.
Read-only native proof export and oracle latency are reported separately. Overall
resource counters include the proof work; business-cycle latency excludes it.
No output number from this driver establishes MRP coverage, concurrent production
capacity, high-volume same-date receipt acceptance, or competitor superiority.
