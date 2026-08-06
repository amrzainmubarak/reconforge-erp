# ADR 0388: Preserve public-network egress as a blocked evidence gate

- **Date:** 2026-08-06
- **Status:** Accepted
- **Scope:** Current-host runtime evidence for the public World Bank connector

## Context

The World Bank connector has a fixed public endpoint, a closed Decimal schema,
and a pinned HTTPS transport. Its live test is intentionally opt-in because
the source can drift and the runtime needs explicit network authorization.

## Decision

Run the opt-in test when the operator enables `RECONFORGE_TEST_PUBLIC_NETWORK`.
If the host cannot reach the pinned public address, record the test as blocked
with the exact transport error. Do not replace the live result with fixtures,
disable address pinning, or call the synthetic transport evidence live.

## Verification

On 2026-08-06 the test reached the pinned connection and failed closed with
`OSError: [WinError 10051]` (unreachable network), surfaced as
`ConnectorNetworkError("connector_transport_failed")`. Schema and digest
assertions were therefore not promoted to live-network evidence.

## Reversibility

No runtime or schema change is required. Re-run the same test from an approved
egress-enabled environment and replace the blocked evidence only after a real
successful response is captured.
