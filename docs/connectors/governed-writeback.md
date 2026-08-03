# Governed write-back lifecycle

ReconForge treats a provider mutation as a proposal, not an implicit side
effect. `reconforge.connectors.writeback` is the provider-neutral contract for
future ERP or banking adapters:

1. Create a digest-bound intent with a tenant/workspace and idempotency key.
2. Keep the feature flag disabled unless an operator explicitly enables it.
3. Require a distinct human checker with step-up or MFA assurance.
4. Dispatch exactly once from the approved state.
5. Bind the provider acknowledgement to the original idempotency key and
   response digest.
6. Request and complete compensation through a separate idempotency key.

The contract stores no payload, credential, destination, or customer record.
An adapter must resolve the digest-bound payload from an authorized short-lived
store, enforce its own manifest egress allowlist, and provide provider-specific
conformance and failure-injection evidence before it can be called live.

This module performs no network I/O and does not constitute a live connector,
payment integration, accounting posting, or production write-back guarantee.

The opt-in `writeback_network` boundary adds a provider-neutral HTTPS POST
adapter for a separately registered endpoint. It resolves a short-lived
payload and credential only for the call, verifies the payload digest, reuses
the same idempotency key on bounded retries, and validates a canonical provider
acknowledgement digest. The built-in connector manifests remain read-only, and
the adapter has only synthetic injected-transport evidence; it is not a live
ERP or banking integration.
