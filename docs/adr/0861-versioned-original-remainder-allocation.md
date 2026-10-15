# ADR0861 — Version original customer-return remainder allocation

Status: implementation contract; not accepted functionality.

## Problem

M7 v1 accepts only positive integral proportions of the original gross and each
original FIFO consumption. Native sales can retain quantities and original
values whose partial proportions are nonintegral. Refusing those returns leaves
M7.6 incomplete. Changing v1 calculations would invalidate captured history,
reviewed plans, retained acknowledgements and IT1 cost-v2 evidence.

## Decision

Keep v1 original facts, fingerprints, history, payloads, APIs and transfer-cost
v1/v2 interpretation. Introduce an additive148 contract for newly born v2 source
owners with one immutable `remaining-original-v1` allocation policy. Use the
existing captured-currency HALF_UP money division for remaining revenue and the
existing FIFO HALF_EVEN allocation with final residual for remaining original
consumption cost. The selected policy is fixed by the server's versioned route.

Recompute active signed original quantity **and value** from chronological
history. Return plans bind remaining-before quantity/value witnesses; reversals
retain the exact original magnitudes and witnesses. Physical layer availability
is a separate constraint and cannot replace the original consumption prefix.

Zero-valued monetary legs produce no journal entry. They still require the
normal three humans, current authorization, atomic physical effects, immutable
history, audit, outbox and replay checks. Nonzero legs retain the existing GL
engine and purpose-based ownership. No zero journal or alternative ledger is
introduced. Legacy v1 continues to require its original positive legs.

The v2 public plan adds the policy and a schema version. The v2 balance adds
`customer-partial-return-balance-v2` and the policy. The new API has an internal
fixed protocol version; v1 filters or refuses v2 objects before its strict
projector. Pending-command retry retains the exact original path and body.

A supplemental immutable FORCE-RLS witness relation preserves historical
restoration row shapes. New IT1 cost-v3 evidence binds the native history
sequence, policy and signed before-value witnesses. Existing cost-v2 arithmetic
and keysets remain strict. Migration replay verifies exact bodies/catalog
metadata, and destructive downgrade refuses retained v2 evidence before mutation.

Restituted inventory can have positive physical quantity and zero residual cost.
Its subsequent native Stock issue uses an explicit restituted-cost policy and
captured IT1-v3 originals. The zero-total issue keeps three humans, physical
movement and approved valuation; it has no COGS entry or effect. A mixed issue
keeps its real positive total COGS. Only an explicit factual original-v2 source
may carry absent original COGS, bound to actual immutable zero consumptions and
the earlier restitution. Legacy original-v1 facts and fingerprints stay strict.
No zero-cost capability is accepted before real resale, return, SQL, HTTPS and
populated restore gates qualify the same integrated source.

An exact closed CR2 physical correction is valued by its original restitution
and financial owner even when it has no generic valuation document. Receipt
chronology must validate that native phase2/history/source/movement ownership,
preserve refusal of unknown unvalued movements, and count later closed corrections
as backdate blockers. A movement namespace or Generated flag alone is insufficient.

## Acceptance

Independently verify FIFO1001/3 partitions111→334,334,333 and21→667,334;
revenue HALF_UP5 split in halves→3,2 against FIFO HALF_EVEN5→2,3; cross-layer and
zero-valued portions; latest reversals; source/policy/witness/command tampering;
concurrency, current authority, SQL bypass, HTTPS and populated restore. Preserve
old v1/v2 golden bytes and all original negative results. This ADR cannot close
M7.6 without those executed gates and cohesive final-head acceptance.
