# ADR-0401: Ownership-change CLI remains local, deterministic, and non-posting

## Status

Accepted — 2026-08-06.

## Context

The ownership-change domain and PostgreSQL evidence boundary already produce a
policy-neutral, replay-verifiable proposal, but an individual operator had no
first-party CLI entry point for the same closed request contract. A CLI must
not silently turn the proposal into a journal, require a server, or accept
ambiguous numeric input.

## Decision

Add `reconforge consolidation ownership-change --input ... [--output ...]`.
The command accepts exactly one bounded JSON request record (directly, or in a
one-element `request` record collection), parses percentages as exact Decimal
text and money as canonical `Money`, invokes the existing pure-domain
preparation function, and writes only the digest-bound result with
`posted: false`. Unknown fields,
binary/non-finite numeric values, currency mismatches, actor violations, and
invalid source/policy lineage fail closed through the shared CLI error path.

The command is local-only and does not persist, post, call a provider, or
mutate an input file. Server persistence remains the separate PostgreSQL API
boundary and still requires its own runtime gate.

## Verification and boundary

Focused CLI/domain tests cover balanced output, non-posting status, digest
presence, output-file handling, and unknown-field rejection. This adds no
statutory accounting judgment, legal-book posting, ERP/bank write-back,
provider interoperability, PostgreSQL live runtime, or production-readiness
claim.

## Rollback

Remove the command, its focused tests, and this ADR. The underlying domain and
PostgreSQL evidence contracts remain backward compatible.
