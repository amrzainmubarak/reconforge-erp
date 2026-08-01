# ADR 0157: PostgreSQL Inventory Core aggregate boundary

- Status: Accepted
- Date: 2026-07-28

## Context

Inventory valuation and reversal require a trustworthy PostgreSQL source of
units, items, locations, lots/serials, and immutable posted movement effects.
The local contract stores quantities as scaled integers with unit-specific
precision and rejects unsafe movement lifecycles.

## Decision

Use one seven-table tenant-bound aggregate under forced RLS. Store quantities
as BIGINT scaled units with explicit precision between zero and six. Use
tenant-qualified foreign keys for every master, period, location, lot, and
movement relationship. Database triggers restrict line mutation to Draft,
allow only Draft-to-Posted-to-Voided transitions, enforce posting/void metadata
and movement direction, and protect finalized headers. Application posting will
add row locks and projected-stock/serial validation before changing status.

## Consequences

Migration 0024 is additive and rolls back child-first. The storage foundation
does not by itself establish Application parity: all eighteen operations,
serialized projected-stock validation, transactional evidence, and a live
non-superuser lifecycle test remain required. Inventory Core stays `absent`
until those gates pass.
