# ADR 0598: Follow the current migration head in the restore drill

## Status

Accepted — 2026-08-23

## Decision

The PostgreSQL write-back identity migration drill validates the restored
database against the current Alembic head (`0090_pg_writeback_observations`),
not the identity migration revision alone. Follow-on migrations must not make
an otherwise valid restore appear to fail. The retained drill and matrix
reports, schemas, and source digests are updated together.

## Boundary

This proves migration reachability and preservation of the write-back guard;
it does not claim production HA/DR, live provider acceptance, or accounting
posting. A future migration must update the declared head and regenerate the
bound evidence artifacts.

## Rollback

Reverting this decision is not allowed without restoring a compatible
migration-head contract and regenerating the retained reports.
