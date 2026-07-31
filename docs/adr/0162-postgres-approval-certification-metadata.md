# ADR 0162: PostgreSQL approval and certification metadata

## Status

Accepted — 2026-07-28

## Context

The Approval Application port stores workflow metadata for governed requests
and independent certification review. These records are not legal signatures,
audit opinions, regulatory certifications, or authority to mutate the target
financial object. Silent reopening, SoD override, or replacement of final
metadata would undermine the evidence trail.

## Decision

Add migration 0029 with tenant-qualified approval-request and certification
metadata tables under forced RLS. Approval requests are created Submitted and
may transition exactly once to Approved or Rejected. Approval requires an actor
different from the requester; rejection requires a reason; override reasons are
always rejected. Submission scope and final decisions are immutable.

Certification metadata is created Prepared and may transition exactly once to
Reviewed by an actor different from the preparer. Scope, preparer evidence, and
reviewed records are immutable. Every successful mutation writes tenant-scoped
audit and outbox evidence in the same transaction. Reads are deterministically
ordered and bounded. No external calls or target-object mutation occur.

## Consequences

The PostgreSQL contract supports the existing eight operations without claiming
delegation, legal signature, or compliance certification capabilities that the
Application port does not provide. Current-live behavior remains unclaimed until
the optional non-superuser lifecycle/RLS test runs against a configured service.
