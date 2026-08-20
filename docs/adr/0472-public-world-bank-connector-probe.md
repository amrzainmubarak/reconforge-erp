# ADR 0472: Record a bounded public open-data connector probe

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The World Bank connector is an intentionally provider-neutral, read-only
reference for public-data interoperability. Synthetic transport tests cannot
detect drift in the real endpoint's response shape or bounded page behavior.

## Decision

Permit the opt-in `RECONFORGE_TEST_PUBLIC_NETWORK=1` test to call the exact
allowlisted World Bank dataset/resource endpoint. Record only the dated
response-schema, finite-Decimal, page-bound, one-attempt, and canonical-digest
observation. Keep the connector classified as a public reference source; do
not count it as an ERP or banking provider.

## Verification

On 2026-08-09, `tests/test_connector_world_bank_public.py` passed 7/7,
including the live page probe.

## Boundary

The endpoint and dataset can drift. This evidence does not establish
authenticated credentials, provider SLAs, payment initiation, ERP/bank
write-back, HA/DR, or production readiness.

## Reversibility

Unset the opt-in environment variable and remove the dated evidence entry. No
application behavior or persisted data changes are required.
