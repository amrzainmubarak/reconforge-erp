# ADR 0203: Signed packs are approved data, not executable extensions

- Status: Accepted
- Date: 2026-07-30

## Decision

Control and industry packages use a closed `signed-data-pack-v1` JSON envelope.
Ed25519 authenticates the complete manifest against an operator-owned, versioned
publisher registry. The manifest embeds only declarative metadata, rules, and a
synthetic golden expectation. Unknown fields, executable entry points, incompatible
platform ranges, invalid dependencies, signature changes, and golden mismatches fail
before admission.

Admission and activation are separate. A maker submits a verified immutable version;
a different actor approves it; an operator installs it. SQLite allows one enabled
version per pack, records actor/digest lifecycle events, preserves disabled versions,
and provides explicit disable and rollback. Upgrade is a new immutable version, not
an in-place mutation.

## Consequences

This is a local, synthetic lifecycle foundation. It does not execute pack-supplied
Python, migrate customer records, provide a public marketplace, or establish publisher
identity beyond keys the operator explicitly trusts. Existing repository YAML packs
and CLI behavior remain unchanged.

## Rollback

Stop admitting packages and remove the lifecycle database. Existing built-in YAML
packs continue to work. If evidence retention applies, export and retain lifecycle
events before removal.
