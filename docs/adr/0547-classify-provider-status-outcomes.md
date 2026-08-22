# ADR 0547: Classify provider status outcomes without lifecycle mutation

- **Status**: Accepted
- **Date**: 2026-08-22
- **Scope**: E-833 provider-neutral write-back idempotency-status recovery

## Context

E-830/E-831 prove recovery by immutable idempotency identity, and E-832 stops
negative responses from becoming acknowledgements. The recovery boundary still
needed an explicit vocabulary for a provider that says the operation is still
processing, cannot find the key, rejects it, or returns an unusable response.
Treating all non-200 responses as one transport error loses evidence and makes
it too easy for a caller to choose an unsafe next transition.

## Decision

Add the provider-neutral outcome taxonomy:

- `accepted`: provider status is positively bound to the original key;
- `rejected`: provider explicitly declines the mutation;
- `pending`: provider or transport says the result is not final yet;
- `not_found`: provider status lookup has no record for the key;
- `unknown`: the response cannot safely establish any of the above.

Expose `observe_recovery()` as a non-mutating boundary that returns a frozen,
canonical `WritebackRecoveryObservation` containing the idempotency key, HTTP
status, SHA-256 digest of the raw response body, provider reference and provider
response digest when available, plus a deterministic observation digest.

`recover()` delegates to that observation path and may advance the immutable
intent only for `accepted`. All other outcomes raise a safe code and leave the
intent in its previous state. The observation object is deliberately separate
from the lifecycle model so adding status evidence does not silently rewrite
historical proposal/intent digests or require an unplanned migration.

Legacy provider responses that only contain `accepted: true|false` remain valid;
the normalized outcome is derived deterministically. An explicitly supplied
outcome is included in the response digest and must agree with the boolean.

## Rationale

Recovery is evidence collection, not a second mutation. Separating observation
from transition preserves the original idempotency identity, makes pending and
unknown outcomes actionable, and avoids guessing whether a provider effect
exists. A future SQLite/PostgreSQL evidence repository can persist the frozen
observation without changing the write-back intent schema.

## Verification

The focused transport/domain selector covers all five outcomes, raw-body and
observation digests, legacy response compatibility, key binding, no-state-
advance behavior, pending recovery refusal, retries, TLS pinning, and the local
HTTPS sandbox. The selector passes 55/55 before the full regression gate.

## Compatibility and rollback

The taxonomy field is optional and digest-compatible for legacy responses. The
public API and persistence schemas remain unchanged; only the additive executor
observation method and internal classification are new. Rollback would remove
the observation model, classifier, ADR, manifest entry, and tests, but would
remove evidence distinctions that are needed for safe provider reconciliation.

## Boundary

The implementation is provider-neutral and synthetic. It does not prove any
vendor's status codes, live authentication, accounting posting, settlement,
distributed delivery, or production recovery objective.
