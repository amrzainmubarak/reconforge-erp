# ADR 0487: Public World Bank connector revalidation

- **Status:** Accepted
- **Date:** 2026-08-10
- **Scope:** `world-bank-public-readonly` reference connector

## Context

ReconForge has a provider-neutral Connector SDK and a no-auth World Bank
reference integration. A current online run is useful evidence for real HTTP,
schema, pagination, digest, and policy behavior, but public data must not be
described as a bank or ERP customer integration.

## Decision

Run the connector's opt-in public-network test against the declared World Bank
endpoint and retain the result only as bounded public-data evidence. The test
must remain opt-in, use no credentials, apply the existing pinned HTTPS and
unsafe-input policy, and verify exact finite-decimal rows, page counts,
canonical response digests, and cross-format parity.

## Evidence

`RECONFORGE_TEST_PUBLIC_NETWORK=1 uv run --no-sync pytest -q
tests/test_connector_world_bank_public.py --tb=long -ra` passes 7/7.

## Consequences

This demonstrates a real public reference endpoint without claiming bank/ERP
interoperability, source authenticity, provider SLA, payment execution,
write-back, hosted deployment, or production operations. Rollback is to disable
the opt-in test and remove this evidence entry; no secret or customer data is
stored.
