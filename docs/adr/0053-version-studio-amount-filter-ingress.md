# ADR 0053: Version Studio Amount-Filter Ingress

- Status: Accepted
- Date: 2026-07-25
- Scope: Read-only Studio exception minimum-amount filtering

## Context

The Studio `/exceptions` HTTP route already declares `min_amount` as text and
the HTML form uses a decimal text input. The underlying `_filter_exceptions`
service type alias and parser still accepted finite binary floats through the
legacy-v1 default. Direct Python callers therefore had compatibility behavior,
while the current web writer relied on call structure rather than a recorded
parser selection.

Filtering changes only which existing exceptions are displayed; it does not
approve, post, persist, or alter a financial decision. Even so, a float-derived
threshold can change the visible candidate set and must not be implicit in the
current Studio path.

## Decision

1. Split the exact current `AmountFilterInput` (`Decimal`, text, integer) from
   `LegacyAmountFilterInput`, which retains finite-float typing for direct
   service compatibility.
2. Add a named `financial_input_policy` to `_filter_exceptions` and
   `_parse_minimum_amount`. Preserve legacy-v1 as the direct Python default.
3. Make the Studio application pass strict-financial-input-v2 explicitly. The
   HTTP/OpenAPI contract remains plain text and rejects scientific notation,
   non-finite, negative, overlong, and binary-float service values under strict
   mode.
4. Extend the AST compatibility perimeter so every production call to
   `_filter_exceptions` must spell the selected policy.
5. Do not persist a filter policy in reconciliation evidence: this is an
   ephemeral read-only presentation query, not an input to matching or a saved
   financial decision.

## Consequences

- Current Studio filtering cannot accept a binary float at its service boundary.
- Existing direct Python callers keep finite-float compatibility and receive the
  existing deprecation warning.
- The single lexical float line remains in the explicitly named legacy alias;
  it is not an unclassified financial arithmetic path.
- No route shape, OpenAPI parameter type, HTML form, database schema, result
  digest, audit event, or persisted artifact changes.

## Rollback

Do not remove the explicit strict policy from the application call or the AST
guard. The service default may change only at a documented breaking-release
boundary with an explicit legacy entry point. If filtering later becomes a
persisted review/report rule, record its policy and canonical threshold beside
that artifact before treating it as reproducible evidence.
