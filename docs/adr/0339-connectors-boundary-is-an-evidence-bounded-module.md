# ADR 0339: Register connector boundaries as an evidence-bounded module

- Status: accepted
- Date: 2026-08-05
- Scope: `P4-CON-001`, `P4-PLAT-001`

## Decision

Register `connectors.boundary` in the runtime module registry. The descriptor
owns the closed connector manifests, provider-neutral read-only network
contracts, signed data-only package admission, and offline CAMT.053 parsing and
payment-statement projection. Its interfaces, data classifications, tests,
retention, and activation limits are explicit; it has no persistence migration
or default network activation.

## Rationale

Connector code had strong individual contracts but no first-class module
descriptor or threat-model parity. A registry entry makes the connector
surface discoverable, maturity-gated, and subject to the same closed threat
and evidence checks as finance, inventory, and workflow modules.

## Evidence boundary

The module remains experimental/foundation evidence. It does not establish
live ERP or bank vendor conformance, source authenticity, credential custody,
payment initiation, settlement posting, autonomous write-back, HA/DR, or
production deployment.

## Rollback

Remove the descriptor, threat-model entry, maturity ceiling, registry tests,
ADR, and execution records. Connector implementations and their direct tests
remain usable as library boundaries.
