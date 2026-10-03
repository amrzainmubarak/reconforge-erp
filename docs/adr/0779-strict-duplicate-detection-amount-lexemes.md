# ADR 0779: Use the strict amount parser in duplicate detection

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Matching

## Context

The bounded duplicate-detection strategy creates canonical fingerprints from
financial amount fields. It already rejected Python binary floating-point
values, but it converted other values directly with `Decimal(str(value))`.
That left a lexical-policy gap: scientific-notation text such as `1e2` could
be accepted by this strategy even though the shared strict financial-input
parser rejects scientific notation at current financial ingress boundaries.

## Decision

Use `parse_exact_amount()` for duplicate-detection amount canonicalization.
The strategy continues to normalize exact values for duplicate fingerprints,
but now shares the strict parser's rejection of binary floating-point,
non-finite, missing, malformed, and scientific-notation text inputs. Wrap the
shared parser error in the existing `DuplicateDetectionError` contract so the
strategy adapter remains backend-neutral and fail-closed.

This decision applies to the amount field used in duplicate fingerprints. It
does not turn duplicate detection into probabilistic matching, financial
posting, fraud detection, or source authentication.

## Consequences and rollback

Duplicate-detection amount acceptance now has one shared lexical boundary with
the rest of the strict financial-input paths, reducing divergent behavior
between matching strategies. Existing exact integer, decimal-string, and
`Decimal` inputs retain their canonical fingerprint behavior. Rollback is a
source/test/ADR/execution-record revert with no database or external-state
mutation.
