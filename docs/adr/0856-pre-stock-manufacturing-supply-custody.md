# ADR 0856 — Original pre-stock manufacturing demand and exclusive supply custody

Status: accepted for experimental owner development; integrated acceptance pending.

An approved engineering BOM can create a real requirement before stock exists.
ME1 reservations already require actual capacity, so reusing them for net shortage
would invent stock custody. Keep immutable planned requirements in a separate
versioned owner, capture exact physical/free FIFO observations at approval, and
place its actual on-hand/received stock claims in the common Core quantity guard.

Preserve existing SRC source format and attach a versioned original planned-demand
companion. Native SRC/RFQ/quotations/deterministic selection/three-human award,
BPC appropriation, PP receipts, AP three-way matching and GL remain their original
owners. Finite live source admission and bidirectional database closure forbid
detached public commands, duplicated shortages or a receipt attached to another
requirement.

Handoff uses an owned native ME1 AFTER INSERT adapter within the existing complete
transaction. It releases source stock guards only after the real native target
exists and before its ordinary reservations/capacity checks. Exact deferred source
phase/event/release/ME2 ACK closure rejects detached use. No special capacity
arithmetic, duplicate engine or shared native signature replacement is required.

Actual production may occur after partial procurement on different business dates.
Record its explicit forward date in the original handoff command and native ME2
request. Preserve every original planning field and digest; only the new native
execution date advances, never before planning or actual acquired receipts.
Native period, effective routing, scope, currency and cost-source invariants still
apply.

This is one bounded order with exact base-UOM scaling and functional currency.
Capacity scheduling, material substitutes, arbitrary conversions, statutory
manufacturing posting and high-volume MRP remain outside this slice. Populated
rollback refuses instead of deleting or silently detaching original evidence.
