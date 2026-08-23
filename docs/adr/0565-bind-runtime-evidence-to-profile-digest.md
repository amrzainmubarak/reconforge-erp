# ADR 0565: Bind runtime evidence to the immutable deployment profile digest

- Status: Accepted
- Date: 2026-08-23
- Decision owners: Deployment Governance / Platform Security

## Context

The runtime-evidence manifest already included an edition and its facts, but a
future profile change could make an old manifest ambiguous unless the exact
profile contract was captured with it.

## Decision

Require `profile_digest` in the closed runtime-evidence manifest. Verification
recomputes the immutable profile digest for the selected edition and rejects a
missing, malformed, or mismatched value before returning evidence. The
manifest's own digest therefore binds the edition, profile contract, and
runtime facts together.

## Consequences

- Evidence can be replayed against the exact profile definition it was created
  for, and profile drift becomes an explicit failure.
- This remains a local integrity check; it does not authenticate the runtime or
  prove an external deployment applies the profile.
