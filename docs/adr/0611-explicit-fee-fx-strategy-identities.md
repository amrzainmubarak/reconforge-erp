# ADR 0611: Explicit fee-aware and FX-aware matching identities

Status: Accepted

## Context

The grouped matcher already implements bounded one-to-one fee netting and
explicit FX conversion.  Exposing those behaviors only as optional fields on
the generic grouped strategy made the public strategy inventory less precise:
callers could not select or audit a fee-aware or FX-aware family by its own
stable identity.

## Decision

Publish two experimental, bounded adapters:

- `bounded-fee-aware-one-to-one@1.0.0`, which requires fee field names and
  forces net-fee arithmetic;
- `bounded-fx-aware-one-to-one@1.0.0`, which requires a target currency and a
  non-empty explicit FX-rate set.

Both adapters delegate arithmetic to the reviewed grouped one-to-one domain
implementation, preserve its explanation schema, carry their own manifest and
input/decision digests, and fail closed on the wrong mode or missing financial
inputs.  Their published ceilings are 64 records per side, cardinality 1x1,
25,000 candidate/search evaluations, and a 3,660-day date window.

## Consequences

The registry and architecture inventory now expose fee-aware and FX-aware
families explicitly, while existing grouped callers remain backward
compatible.  This is bounded synthetic matching evidence only; it does not
validate live rates, posting, write-back, or production throughput.
