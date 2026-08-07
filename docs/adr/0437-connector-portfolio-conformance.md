# ADR 0437: Require common conformance replay for provider read manifests

- Status: accepted
- Date: 2026-08-07
- Scope: `P4-CON-001`, `connectors.boundary`

## Decision

Keep provider-specific connector behavior behind the shared Connector SDK
conformance boundary. The reference portfolio now includes the bounded
CAMT.053 HTTPS source and both ERPNext read sources. Each network registration
must pass the common manifest checks and a deterministic synthetic replay using
the governed executor, including exact HTTPS egress, secret-reference auth,
bounded retry/cursor declarations, identical request/response digests, and
bounded recovery from declared transient statuses.

## Evidence boundary

The portfolio test uses an in-process synthetic transport and a synthetic
secret resolver. It proves SDK contract alignment and replay determinism only;
transient retry behavior is injected in-process and is bounded to each
manifest's declared attempt ceiling. It does not prove a live bank or ERPNext tenant, provider dialect/version
compatibility, source authenticity, certificate or credential operations,
settlement, posting, write-back, or production availability.

## Rollback

Remove the portfolio imports, replay test, this ADR, and the execution/claim
records. The provider-specific adapters and their direct tests remain
unchanged.
