# ADR 0576: Current PostgreSQL consolidation-close runtime evidence

## Status

Accepted — 2026-08-23

## Context

The global close/consolidation track requires evidence that the governed close
lifecycle works in the server profile, not only in SQLite or static contracts.

## Decision

Run the PostgreSQL close, consolidation-close, and server HTTP lifecycle suites
against the disposable PostgreSQL 16.14 service using the `reconforge_app`
application role. Count this as bounded runtime evidence only when the suite
passes with tenant isolation, replay identity, maker-checker separation,
period lock/reopen, certification evidence binding, reversal controls, and
server route scope checks.

## Limits

The run uses synthetic data on one local host and a non-privileged role. It does
not establish statutory accounting, legal close compliance, external ERP
posting, production approval, hosted parity, HA/DR, or independent assurance.
