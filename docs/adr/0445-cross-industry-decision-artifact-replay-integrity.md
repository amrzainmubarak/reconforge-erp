# ADR 0445: Share nested decision-artifact replay checks across industry controls

## Context

The bank-statement, manufacturing-cost, and professional invoice/payment
controls emitted a `decision_digest` inside their reports, but their readers
validated only the outer artifact envelope. That left the serialized decision
projection and status counts unchecked after an outer rehash.

## Decision

Add one small, provider-neutral domain helper that verifies the serialized
decision contract without rebuilding source records. Each control keeps its
own schema/algorithm versions, digest field list, decision ordering, and
allowed statuses. The producer and reader use the same canonical digest
function. Readers run nested verification after the existing outer digest.

The helper also requires sorted unique input fingerprints and status counts
derived from the serialized decisions. It does not add network I/O, persistence,
posting, provider authenticity, or write-back behavior.

## Evidence and boundary

Focused bank, manufacturing, and professional-control suites pass 21 tests,
including one outer-rehash tamper regression per module. This is serialized
artifact-integrity evidence only; it is not a source-authenticity signature,
live settlement proof, statutory accounting, or production-readiness claim.
