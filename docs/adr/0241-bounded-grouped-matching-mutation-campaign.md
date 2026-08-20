# ADR 0241: Publish a bounded grouped-matching mutation campaign

- Status: accepted
- Date: 2026-08-02

## Decision

Add a deterministic request-level mutation campaign for three critical
grouped-matching changes: one-cent amount increase, one-cent amount decrease,
and disabling explicitly allowed partial settlement. Each mutant must change
the public decision digest; a surviving mutant fails the campaign.

## Boundary

The campaign is a targeted financial regression sentinel, not a source-code
mutation engine score. It uses synthetic requests and does not prove
PostgreSQL runtime parity, fuzzing, or mutation coverage of unrelated modules.

## Rollback

Remove the campaign, tests, report, ADR, and package entries. Matching runtime
behavior is unchanged.
