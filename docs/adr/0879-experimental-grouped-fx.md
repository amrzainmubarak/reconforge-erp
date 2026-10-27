# ADR 0879: Experimental bounded FX matching

Status: experimental; not accepted for production or financial posting.
Date: 2026-10-27

## Context

The existing PostgreSQL grouped adapter rejects an inverse conversion requiring an inexact reciprocal even when currency conversion has a valid rounded amount. Existing v1 digests are also sensitive to Decimal context and must not be silently rewritten. The current guard fails closed, and no evidence establishes that the default production runtime selects this adapter.

## Decision

Add a separate non-posting one-to-one domain entry point with its own algorithm identifier. The caller supplies an immutable currency registry snapshot, original rates with source, type and validity interval, target currency, matching policy, and an explicit per-record/per-component rounding scope. Conversion uses exact fractions and one target-currency rounding. A bounded independent candidate check rejects changes in eligibility or best ordering caused by rounding rather than silently choosing an outcome. Returned decisions bind original records, rates, policy, registry and conversion evidence to their FX-specific digest. Unsupported and ambiguous rate profiles fail closed.

This intentionally excludes multi-record grouped FX, persisted run selection, cross-version replay, transaction boundaries, authorization, and canonical financial posting. The new function is not wired to the worker, API or UI. It does not change previously recorded v1/v2 results. Separate pair verification has a maximum of 4096 evaluations and is additionally bounded by the requested search budget; it is in addition to the existing kernel search.

## Verification and remaining gates

Focused examples, exact rational oracle checks and independent review cover rounding collisions, missed candidates, changed ranking, original-rate direction, fees, currency precision, validity, evidence binding and input bounds. This evidence is not a PostgreSQL or end-to-end business result. Before operational use, require a versioned immutable run/registry binding and checkpoint validation, backend-native storage and migration/restore tests, independent currency-policy review, tenant authorization, safe replay and rollback tests, and source-frozen CI. Keep the release blocked.

## Rollback

Do not select the experimental entry point. Existing v1 and v2 decisions and stored artifacts remain untouched. No historical financial entries or evidence are rewritten.
