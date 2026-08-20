# Redis-backed policy-cache invalidation

This is an explicit server-profile optimization. It is not enabled by the
Community/local default. Configure Redis with TLS in a deployed environment
and enable the API policy cache only after reviewing the outage boundary.

When enabled, API processes keep decisions locally and share only a monotonic
generation key. Any non-safe request increments that key; other processes stop
using entries from the prior generation on their next authorization check.

The generation key contains no user, tenant, permission, or financial data.
Redis errors cause the affected process to evaluate policy without its local
cache. An invalidation increment failure is an operational degradation: keep
the policy cache disabled until Redis health is restored and recycle workers if
local cache state must be discarded immediately.

This contract uses coarse global invalidation. It does not provide Redis HA,
cross-region durability, pub/sub delivery, complete route/job/export/UI
migration, or production IAM assurance.
