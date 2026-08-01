# ADR 0183: Emergency authority is temporary, session-bound, and review-mandatory

Date: 2026-07-29

Status: Accepted

## Context

Ordinary RBAC and recent reauthentication can still leave incident responders
without the narrowly required authority. A hidden override, reusable elevated
role, or unaudited break-glass token would defeat least privilege and maker-
checker controls.

## Decision

- Emergency access is available only in the explicit PostgreSQL server profile
  and only to human principals.
- A requester may request authority only for their own identity and only from a
  closed five-permission registry. Identity, policy, role, service-account, and
  security administration are excluded.
- An independent stepped-up approver must approve or reject the request.
- The requester must activate an approval from the same current stepped-up
  session. Authority lasts 5–60 minutes, cannot outlive that session, and is
  re-evaluated on every request.
- Emergency permissions remain distinguishable from base RBAC. Every
  emergency-derived authorization appends a route, permission, actor, and
  request-reference event before the protected operation proceeds.
- End or expiry enters `ReviewPending`; an independent stepped-up reviewer must
  record an outcome and note. The requester and approver cannot review.
- Requests, grants, and deterministic event order are protected by forced RLS,
  state constraints, immutable permission rows, no-delete request evidence, and
  append-only events.

## Consequences

This provides bounded, evidence-backed emergency authority; it does not provide
MFA, production privileged-access management, hosted operational approval, or
independent assurance. P3-ENT-003 remains in progress for those broader identity
and operational controls.

## Rollback

Downgrade migration 0039 to 0038. This removes the emergency-access tables and
API backing state, so evidence export/retention approval is required before any
real deployment rollback. No production rollback was performed in this slice.
