# ADR 0793: Return the authenticated user's permission snapshot

Date: 2026-10-03. Status: accepted. Scope: financial UI prerequisite.

`/auth/me` returned permission names for service accounts but omitted them for
humans. A financial UI must not infer authority from a role label or require
role-administration access merely to show invoice actions. Add the current
server principal's permission names to human responses; local mode queries the
existing role repository on each request. Use the already-allowed projection
field, keep the list sorted, and expose no credential/session identifiers.

This is an additive API field, not authorization for an action. Scope, amount,
period, maker/checker and step-up policy still run on the server per operation.
Financial approval is already human-only through the `.approve` suffix policy;
this slice does not change which actions require step-up.

Regression tests cover local revocation with an unchanged role, human/service
request-authority parity, foreign tenant rejection and sensitive-field removal.
Focused auth/projection/browser tests: 66 passed, one optional live prerequisite
skip; server identity: three passed, one live prerequisite skip. Real financial
browser flows remain a separate acceptance gate. Rollback removes the additive
field; UI clients must treat a missing field as unavailable capability data.
