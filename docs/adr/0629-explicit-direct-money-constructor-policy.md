# ADR 0629: Require explicit policy on direct production Money construction

- Status: Accepted
- Date: 2026-08-25
- Scope: Direct `Money(...)` calls under `reconforge/`

## Context

The repository already requires production `Money.from_exact(...)` calls to
declare their precision behavior and requires direct `Money(...)` calls to
declare the input policy. Direct constructors are less common but remain a
high-risk financial ingress because an omitted precision flag can change
whether over-precise input is rejected or rounded.

## Decision

Extend the existing financial-input AST contract so every direct production
`Money(...)` call outside the money implementation must provide an explicit
`strict_precision` keyword in addition to the existing explicit `input_policy`
requirement. The value may be a typed policy parameter propagated by a helper,
or an explicit boolean at the call site. Both `True` and `False` remain allowed
because legacy compatibility readers are named and policy-bound; the contract
prevents implicit behavior, not an intentional compatibility choice.

## Consequences

New direct constructor call sites fail the financial policy test until their
precision choice is reviewed in code. Existing behavior and public compatibility
are unchanged. The test does not classify non-financial `float` values, nor does
it replace runtime validation of dynamic constructor inputs.

## Rollback

Revert the test and this ADR if direct construction is removed or replaced by a
different typed ingress contract. Do not weaken the check by accepting a
non-literal default; migrate callers to an explicit policy instead.
