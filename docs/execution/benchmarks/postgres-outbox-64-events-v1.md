# PostgreSQL outbox 64-event profile

The profile uses four independent workers, one tenant queue, batches of eight,
and 64 synthetic events. It proves exactly-once *observed sink effect* for the
bounded claim/publish/acknowledge cycle: all event IDs are seen once, and the
PostgreSQL pending/claimed/dead counts are zero after the drain.

This is not a broker, external provider, crash-after-publish, queue-HA,
throughput, soak, or production-readiness claim.
