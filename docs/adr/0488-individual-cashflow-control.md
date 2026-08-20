# ADR 0488: Individual and freelancer cashflow control

- **Date:** 2026-08-10
- **Status:** Accepted for the experimental local slice
- **Decision:** Add a provider-neutral `individual.cashflow` module with exact
  `Money` aggregation by period, flow type, and category; optional category
  budget lines; replay-verifiable decision and artifact digests; a local CLI;
  and an authenticated stateless local API. Ship a declarative control pack,
  examples, JSON Schema, threat-model entry, and a strict read-only English/
  Arabic Modern Studio projection with WCAG route coverage.
- **Rationale:** ReconForge needs a real individual/freelancer path in the
  breadth portfolio without turning the core into an ERP, requiring network
  access, or inventing a posting/tax/bank claim.
- **Non-goals:** Bank authentication, live connectors, tax or legal advice,
  statutory/legal-book posting, journal mutation, write-back, hosted
  persistence, HA/DR, and production availability.
- **Verification:** Focused domain, CLI, API, registry, threat-index,
  authorization-inventory, and Studio component tests pass locally; web
  typecheck, production build, and the accessibility route gate cover the
  projection. The full regression and package gates remain required before
  any release decision.
- **Rollback:** Remove the module registration, API/CLI exposure, pack,
  examples, schema, tests, ADR, and documentation entries. No migration or
  external data is created by this slice.
