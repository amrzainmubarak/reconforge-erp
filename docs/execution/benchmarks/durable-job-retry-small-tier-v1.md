# Durable-job retry small-tier profile

The `durable_job_retry` harness injects a synthetic transient fault after at
most one committed partition, then exercises the existing retry transition
under concurrent SQLite workers. The resumed worker reads committed partition
effects and skips them.

The required structural checks are:

- every declared job completes without terminal failure;
- scheduled retries equal the injected fault count;
- partition effects equal jobs times partitions;
- duplicate `(job_id, partition_key)` effects are zero;
- queued/retrying/running depth drains to zero;
- retry count never exceeds the declared ceiling; and
- effect and manifest digests are present and replayable;
- delayed retry attempts follow bounded exponential backoff per retry attempt index:
  `delay = min(max, base * (2**attempt))` with observed samples recorded.

Runtime, throughput, and memory are deliberately not part of the digest. This
is a small SQLite-only profile, not a PostgreSQL capacity, external-side-effect
compensation, or 10K/100K/1M/10M scale claim. Provider-managed backoff policy,
tenant-level fleet spread, and production retry-tuning are not claimed.
