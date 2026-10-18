# ADR 0765: Strict canonical ERPNext write-back amounts

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: ERPNext Journal Entry and Payment Entry write-back drafts used
  local `Decimal(value)` validation and retained source formatting. Equivalent
  financial inputs could therefore produce different provider payload bytes
  and approval-bound `payload_digest` values.
- **Decision**: Route write-back debit, credit, paid, and received draft fields
  through `canonical_connector_amount()`. Use strict parsed values for
  one-sided and balance invariants, and serialize the validated draft with
  canonical plain amount text before calculating `payload_digest`.
- **Rationale**: A write-back payload is a financial effect proposal and its
  digest is the identity bound to approval and idempotent dispatch. Equivalent
  amounts must have one deterministic payload while binary, scientific,
  malformed, non-finite, and invalid negative values remain refused.
- **Safety boundary**: This changes draft validation/serialization only. The
  registration remains feature-disabled by default, provider I/O remains behind
  the governed write-back executor, and maker-checker, policy, scope,
  idempotency, acknowledgement, and compensation contracts are unchanged.
- **Compatibility**: Field names, payload schema, operation identifiers, and
  provider endpoint contracts remain unchanged. Newly built drafts use
  canonical amount text and consequently may have a different payload digest;
  callers must continue to build the approval intent from the returned payload
  digest. Existing persisted intents remain byte-bound and are not silently
  rewritten.
- **Verification**: Journal and Payment Entry tests cover canonical payloads,
  equivalent-input digest convergence, scientific/non-finite/negative refusal,
  balance and one-sided invariants, human approval, disabled-default behavior,
  idempotent dispatch, TLS retry, secret isolation, and provider payload
  identity. Full regression and release gates are recorded in E-1105.
- **Rollback**: Revert E-1105, ADR 0765, write-back connector/test changes,
  manifest entry, and execution records together. Do not mutate persisted
  intents during rollback.
