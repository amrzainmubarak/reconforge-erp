# ADR 0839: Inventory receipt API command actor affinity

Status: Accepted for the additive authenticated receipt API.

## Context

The retained receipt command records already identify the human who prepared,
reviewed or committed the source. Existing internal repository callers allow a
different currently authorized human to recover the same exact retained result
by replaying its command. Tests explicitly cover this compatibility contract.
The new browser API retains a pending command across uncertain acknowledgements;
that mutation retry should remain bound to its original authenticated human.

## Decision

Both SQLite and PostgreSQL receipt owners expose an optional
`strict_command_actor` setting, defaulting to `False` to preserve inherited
internal callers. The new receipt API enables this setting. A retained command
with identical scope and intent can be replayed only when its stored actor ID
matches the current authenticated principal. Normal authority, step-up and scope
checks still precede the retained-command lookup. A mismatch returns the stable
`inventory_receipt_command_actor_denied` error (HTTP 403) and rolls back the
complete command. Different content retains the existing conflict response.

Authorized GET recovery remains shared: another reviewer can inspect the exact
verified source, review and effect without impersonating the original retry.
Original-human retries remain idempotent and preserve the canonical financial
history, artifact IDs, audit events and outbox events. This decision adds no
schema changes and rewrites no retained evidence. It covers preparation, review,
commit and inverse preparation through the owners' shared command lookup.

## Verification and rollback

SQLite regressions replay preparation, review and commit as a third authorized
human, verify denial with the entire database dump unchanged, verify original
human retries and shared read recovery, and prove the default adapter contract
remains compatible. The real restricted-role PostgreSQL HTTPS journey exercises
different-human replay denials, original-human retries, shared recovery and the
full unused inverse. PostgreSQL evidence requires the explicit owned live
fixture prerequisite and is not inferred from an environment without it.

Rollback disables the optional setting on the additive API owner construction;
the stored command records and inherited adapter contract are unchanged.
