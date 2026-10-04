# Scoped PostgreSQL exception review

Status: accepted for the bounded server review slice.

Date: 2026-10-04

The inherited exception queue had a PostgreSQL repository and retained history,
but the server API explicitly refused the surface. It had no request-bound
organization/legal-entity scope, no version requirement, no actor identifier or
decision reason in history, and no governed server transition contract.

Revision `0104_pg_exception_review_api` preserves existing records while adding
optional canonical organization and legal-entity attribution, actor and reason
evidence, forced RLS, a hierarchy index, structural history guards, and the
existing audit/outbox transaction path. It seeds the existing and subsequently
created standard identity roles with the already named `exceptions.read` and
`exceptions.manage` permissions without reactivating a revoked grant. A
populated downgrade refuses to discard scoped records or review evidence.

The server surface is deliberately a typed application boundary. Every request
requires an authenticated tenant and workspace grant; organization and legal
entity headers, when selected, are verified against the current principal and
narrow both central policy evaluation and PostgreSQL RLS. This preserves
workspace-scoped access to historical records that cannot be safely attributed
to an organization or legal entity. Such records do not become visible through
a narrowed organization or entity request.

Commands carry a positive expected version. The permitted lifecycle is `Open`
to `In Review`, then to `Resolved` or `Accepted Risk`, then to `Closed`.
`Accepted Risk` requires a retained reason. The creator cannot be assigned as
the reviewer or make a decision transition. A successful command writes the
state, immutable history, append-only domain audit event, and transactional
outbox event in one PostgreSQL transaction. Read responses use closed record
and history projections.

This decision is supported by pure invariant/application tests, a closed HTTP
contract test, a full authenticated HTTP acceptance test against a disposable
PostgreSQL database and a non-superuser/non-`BYPASSRLS` application role, and
frozen migration/upgrade/downgrade tests. The bounded proof does not establish
automatic escalation, a standalone UI, native backup orchestration, production
capacity, availability, regulatory compliance, or individual human identity
enforcement inside a shared runtime database credential.
