# ADR 0181: Machine principals cannot perform human-governed decisions

Date: 2026-07-29

Status: Accepted

## Context

Issuing a bounded service credential is insufficient if the HTTP layer converts
the machine into a normal user. That conversion would permit role lookup,
self-approval assumptions, or human workflow actions to bypass the intended
service-account permission ceiling.

## Decision

- The authenticated server principal carries an explicit `user` or
  `service_account` type. Service credentials never create a user session or
  consult user-role membership.
- Tokens with the reserved `rfa_` prefix are authenticated only by the
  forced-RLS service-account repository. Human session lookup does not accept
  them as a fallback.
- Machine authorization uses only the active account's current direct
  permissions. The routing tenant is validated again inside the database
  transaction.
- The central policy engine rejects every explicit human-governed permission
  and every permission ending in `.approve`, `.review`, or `.complete` for a
  service principal, even if corrupt or legacy state appears to contain it.
- Dynamic workflow transitions are human-only. Service-account logout revokes
  the presented credential rather than a synthetic user session.
- Authorization evidence records the sanitized principal type. Alembic keeps
  existing application loggers enabled so migration execution cannot silently
  disable later policy-audit evidence.

## Consequences

Machine clients can call bounded non-human HTTP operations using explicit
least privilege and can deterministically revoke the presented credential.
Privileged human sessions, step-up authentication, emergency-access expiry and
review, workload identity federation, hosted operation, and independent review
remain outside this slice. P3-ENT-003 therefore remains in progress.

## Rollback

Revoke all service credentials and disable service-account HTTP composition.
The migration-0037 lifecycle remains usable from the operator CLI. Reverting
the typed-principal composition restores the prior user-session-only API without
changing stored user, federation, SCIM, or service-account records.
