# ADR 0364: Bounded retail POS settlement control slice

- Status: Accepted for the experimental local slice
- Date: 2026-08-05
- Decision owners: ReconForge maintainers

## Context

The platform breadth backlog needs a real retail use case without turning
ReconForge into a generic POS or payment system. Existing matching and rules
primitives can provide a useful first control if the financial and provider
boundaries remain explicit.

## Decision

1. Add a typed, pure-domain `retail-pos-settlement-v1` algorithm for exported
   POS batches and exported processor settlements.
2. Require exact `Money` values, one currency per run, non-negative source
   amounts, unique IDs, deterministic ordering, and a caller-supplied exact
   tolerance.
3. Keep missing POS/settlement records, duplicate provider rows, scope
   mismatches, fees, chargebacks, refunds, and net variances visible as
   explicit decision statuses; never auto-collapse ambiguity.
4. Expose a local CLI and digest-bound JSON artifact. No network call, journal
   posting, provider acknowledgement, or write-back is part of this slice.
5. Register the slice as an experimental runtime module and ship a matching
   declarative CSV control pack with synthetic fixtures.

## Consequences

The module is useful for a store/controller's exported daily settlement review
and provides a concrete contract for future provider adapters. It deliberately
does not satisfy the full retail breadth exit gate: persistence/API/Studio,
live provider conformance, settlement finality, card-network semantics,
operations/HA, and independent domain validation remain open.

## Rollback

Remove the module descriptor, CLI registration, domain/application files,
fixtures, pack, schema, docs, and focused tests in one reviewed commit. The
existing reconciliation and connector boundaries are unaffected.
