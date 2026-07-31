# Enterprise reliability runbook index

This document governs the bounded ReconForge reliability policy v1. Measurements
are non-negative integers without tenant, workspace, record, amount, currency, or
actor labels. Missing measurements produce `no_data`; they never imply health.
The thresholds below are initial operator defaults, not measured production SLOs.

| ID | Signal | Warning / critical | Required action |
|---|---|---:|---|
| RF-OPS-001 | API error basis points or p95 milliseconds | 100/500 bps; 1000/3000 ms | Preserve request/trace IDs, check readiness and dependencies, stop unsafe mutations if integrity is uncertain, then verify recovery with a fresh synthetic request. |
| RF-OPS-002 | queued jobs or oldest queued age | 100/1000; 300/1800 s | Pause producers where supported, inspect lease/retry/dead-letter evidence, restore the worker dependency, and prove backlog decreases without replaying committed effects. |
| RF-OPS-003 | dependency readiness failures | 1/2 | Treat the service as not ready, isolate the failed dependency, use its specific recovery runbook, and require a clean readiness probe before traffic returns. |
| RF-OPS-004 | audit verification failures | 1/2 | Stop approvals and evidence export, preserve artifacts read-only, run audit verification, escalate as an integrity incident, and do not rewrite the chain. |
| RF-OPS-005 | process memory MiB | 2048/3072 | Apply backpressure, retain job checkpoints, capture bounded capacity evidence, and restart only through the documented recovery path. |

For every incident, record UTC start/end, policy version, alert state, safe
correlation identifiers, commands used, evidence digests, decision owner, and
residual risk. Never paste raw financial rows or credentials into incident logs.
Recovery requires the triggering signal to return to `normal`, all required
signals to be present, and the affected business invariant to pass a synthetic
check. A green local exercise is not HA, production SLO, compliance, or external
assurance evidence.

The reference incident record follows the ordered lifecycle `detected` ->
`acknowledged` -> `mitigating` -> `recovered` -> `closed`. Events are append-only,
monotonic, and hash-chained. Use safe role/operator references and evidence
digests only; raw commands, credentials, tenant identifiers, and financial rows
do not belong in the record. Recovery validation must be performed by a distinct
operator where staffing permits and requires every policy signal to be present
and normal. Run the local exercise with:

```text
python .github/scripts/verify_reliability_incident.py \
  --output docs/execution/RELIABILITY_INCIDENT_LOCAL_DRILL_2026-07-30.json
```

Its synthetic operator references and in-process acknowledgement do not prove a
real on-call roster, external pager delivery, durable incident retention, or
independent operational assurance.

For the local profile, run `reconforge ops reliability --db <path>`. Use
`--require-complete` in an operator gate: it exits non-zero for warning, critical,
or `no_data`. A one-shot CLI has no HTTP request window, so that source remains
`no_data`; use the explicitly injected bounded window in the API runtime when HTTP
SLO evaluation is required.

To export traces, metrics, and closed operational events, install the `observability` extra and start the API
with an explicit origin, for example:

```text
reconforge api serve --db output/reconforge.db \
  --otlp-http-endpoint https://collector.internal.example:4318 \
  --otlp-allowed-host collector.internal.example \
  --otlp-certificate-file /run/reconforge/collector-ca.pem
```

Plain HTTP is accepted only for loopback drills. For mTLS, provide both
`--otlp-client-certificate-file` and `--otlp-client-key-file`. Ambient OTLP and
proxy environment variables are not trusted. Omit the endpoint for the default
no-export/no-egress behavior. OTLP log records are restricted to validated event
codes and allowlisted attributes; arbitrary application log messages are not
forwarded. Standard logs still carry request/trace/span correlation locally.

The reference Collector configuration is `docs/operations/otel-collector.v1.yaml`.
The verified image subject is:

```text
ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib@sha256:93aad750175cbf1a973ae1c5886c3371f4d800f61be25cdd26870b8441ffe9fa
```

Bind port 4318 to a private or loopback interface, mount configuration read-only,
provide an operator-owned writable backend directory, use a read-only root filesystem,
drop capabilities, and set `no-new-privileges`. The included file exporter is a
bounded sovereign reference sink, not a retention or HA design; replace it only
through an approved backend policy and preserve the exact egress allowlist.
