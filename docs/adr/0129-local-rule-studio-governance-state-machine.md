# ADR 0129: Local Rule Studio governance state machine

- Status: Accepted
- Date: 2026-07-28

## Context

P2-006 requires draft, version, diff, test, and approval behavior without
allowing an unreviewed rule to be published. A visual editor that merely changes
JSON would not provide evidence that the tested content is the approved content.

## Decision

Rule Studio uses an in-session `draft -> tested -> approved` state machine. Any
edit clears test and approval evidence. Tests parse a closed 64-KiB JSON object,
require schema version 1, exact-decimal strings, bounded unique synthetic cases,
and an allowlisted exact/tolerance strategy. Matching uses scaled `BigInt`
arithmetic rather than binary floating point. A SHA-256 digest binds the tested
canonical rule to approval. Approval requires a passing result for the same
digest, a non-empty reason, and a reviewer different from the author. A new
version is created explicitly and begins again as a draft.

No publish, install, API write, filesystem write, or persistence action exists
in this foundation. The browser flow is an experimental governance preview, not
the authoritative Reconciliation-as-Code release mechanism.

Routine E2E captures are held in memory. Documentation screenshots are updated
only when `RECONFORGE_UPDATE_SCREENSHOTS=1`, eliminating Windows file-lock flakes
and unintended repository mutations during verification.

## Consequences

- Structured diff paths, exact golden-case results, digest binding, SoD, version
  reset, English/Arabic UI, RTL, and keyboard-native controls are tested.
- JSON duplicate-member detection, durable drafts, authentication, signatures,
  server-side replay, approval audit, and publication remain outside this local
  foundation and are required before any production rule lifecycle claim.
- Rollback removes the additive route and state module; there is no stored data.
