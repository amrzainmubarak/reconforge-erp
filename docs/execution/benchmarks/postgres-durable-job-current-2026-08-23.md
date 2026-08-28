# PostgreSQL durable-job backpressure and repeated soak — 2026-08-23

## Boundary

This is a bounded synthetic runtime against the local PostgreSQL service using
the non-privileged `reconforge_app` role (`NOBYPASSRLS`). It combines the
backpressure tier and three repeated small soak iterations in one evidence
artifact. The artifact records the exact environment, effect digests, queue
drain state, and explicit limitations.

## Result

- Backpressure: 64/64 jobs and 256/256 partition effects, zero duplicates,
  final queue/running depth zero, observed maximum queue depth four, and 20
  bounded-submit rejections.
- Repeated soak: 3/3 iterations, 192/192 jobs and 768/768 partition effects,
  zero duplicate effects, zero non-drained runs, and identical effect digests
  across all three iterations.
- Observed runtimes were 1.3721 seconds for backpressure and 10.5113 seconds
  for the repeated soak on Windows 11 / Python 3.14.6 / 16 logical CPUs.

The digest-bound JSON artifact is
`postgres-durable-job-current-2026-08-23.json`.

## Verification

```text
RECONFORGE_TEST_POSTGRES_DSN=postgresql://reconforge_app:***@127.0.0.1:5432/postgres
python -m pytest -s -q tests/test_postgres_durable_jobs.py -k "live_postgres_durable_job_soak_profile or live_postgres_durable_job_backpressure_profile"
```

The run passed both live tests with no skip. The local service was cleaned by
the test fixtures.

## Limitations

This does not prove distributed or multi-host soak, queue HA, automatic
failover, host loss, cross-host fairness, capacity, throughput SLOs, RPO/RTO,
provider behavior, or production readiness.
