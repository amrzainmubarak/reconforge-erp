# ADR 0342: Keep competitive comparisons official-source and evidence-bounded

- **Date**: 2026-08-05
- **Status**: Accepted

## Context

The execution goal includes an ethical comparison with open-source and
commercial ERP/financial platforms. Existing strategy material is useful as a
historical view, but a current comparison needs a short, auditable source list
and an explicit separation between competitor documentation and ReconForge
runtime evidence.

## Decision

Publish `docs/strategy/official-source-competitive-matrix-2026-08-05.md` as a
dated supplement. It may record only narrow observations supported by
first-party documentation and must map ReconForge observations to code, tests
or evidence IDs. It must not infer performance, security assurance, customer
outcomes, pricing, regulatory status or product superiority. Missing evidence
is recorded as an open gap.

## Consequences

- Product decisions can distinguish documented market capability from verified
  repository capability.
- The matrix remains useful without copying proprietary designs or making
  unsupported marketing claims.
- Live providers, independent HA/DR, statutory accounting, complete IAM
  adoption and industry breadth remain explicit workstreams rather than being
  closed by documentation.

## Verification and rollback

`tests/test_official_competitive_matrix.py` checks the required official links,
bounded-language guardrails and the presence of local evidence references.
Rollback removes the supplement, this ADR, the regression test, package
entries and the corresponding execution-log records; it does not alter runtime
data or migrations.
