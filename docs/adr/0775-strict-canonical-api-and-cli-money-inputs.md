# ADR 0775: Enforce exact canonical Money at API and CLI input boundaries

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Interfaces / QA

## Context

The API request models and the intercompany CLI contract declare their nested
values to be canonical Money objects. Their adapters still called the
compatibility restoration reader, which could normalize a policy-valid padded
amount or lowercase currency before building a typed request. That left an
interface boundary accepting data that was not the producer's canonical
serialization, even though the resulting artifact would later be canonical.

## Decision

Use `Money.from_strict_canonical_dict()` in the five consolidation API request
adapters and in the intercompany elimination CLI. Keep the existing
compatibility reader for explicitly compatible restoration paths, and keep the
ownership-change CLI's legacy two-field Money input contract unchanged because
it is not a canonical Money-object contract.

## Consequences and rollback

Valid canonical clients and CLI requests are unchanged. Padded/scientific
amount text, lowercase currency, or altered Money provenance is rejected at
the interface before domain arithmetic. This is a validation tightening of
declared canonical input contracts, not a schema-version or financial-data
migration. Rollback is a reversible source, test, documentation, and manifest
revert.
