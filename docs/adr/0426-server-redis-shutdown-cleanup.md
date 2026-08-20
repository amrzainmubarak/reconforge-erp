# ADR 0426: Close the server-profile Redis client at application shutdown

## Status

Accepted for the current server-profile boundary.

## Context

`create_api_app` already registers shutdown cleanup for the bounded PostgreSQL
connection pool. The optional Redis client is also a reusable pooled client,
but the application did not register its `close()` callback. A process reload
or graceful worker shutdown could therefore leave Redis sockets open until the
runtime collected them.

## Decision

When `redis_url` is configured, register the existing
`RedisConnectionFactory.close` callback on the FastAPI router shutdown hooks.
Keep Redis lazy and optional; local mode remains unchanged and no Redis
connection is opened merely by constructing the application.

## Verification and boundary

The API foundation contract verifies that the configured Redis factory has a
shutdown callback. This proves lifecycle registration only. It does not prove
Redis availability, replication, failover, HA/DR, throughput, or production
SLOs.
