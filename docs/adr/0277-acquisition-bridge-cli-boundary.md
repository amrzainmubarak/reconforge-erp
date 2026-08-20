# ADR 0277 — Acquisition bridge CLI boundary

- **Status:** Accepted
- **Date:** 2026-08-03
- **Scope:** Local operator preparation of acquisition evidence

## Decision

Expose a read-only `reconforge consolidation acquisition-bridge` command. It
accepts exactly the versioned JSON request contract, reconstructs canonical
`Money` values under the configured currency policy, invokes the pure-domain
bridge, and prints or writes the replay-verifiable result. Unknown fields,
malformed money, and policy violations fail closed.

## Rationale

The bridge is useful only if operators can reproduce it without importing
Python internals. A strict JSON boundary makes the CLI automation-friendly
while preserving the domain calculation as the single source of truth.

## Compatibility and limits

The command is additive, local, and has no network or database side effect. It
does not approve, post, reverse, certify, or write back an acquisition; it is
not a statutory accounting workflow, legal opinion, or production integration.

