# Deployment Boundaries

Implemented:

- API and Studio default to localhost binding.
- `reconforge deployment release-check` performs a local DB migration smoke check and output directory write check.
- `reconforge deployment docker-verify` checks local Docker file/tooling presence.
- `reconforge deployment profiles` prints immutable Community/Team/Enterprise/
  Regulated defaults, a digest, and an explicit claim boundary. It is a
  read-only contract; it does not infer that a deployment is production-ready.
- `reconforge api serve` can optionally serve a built Studio and `/api/v1/*`
  from one exact-host-allowlisted origin with either direct TLS files or an
  explicit reviewed-upstream-TLS assertion. CSP, HSTS in secure mode, frame
  denial, MIME sniffing denial, referrer policy, and permissions policy apply
  to both surfaces. ADR 0200 and the same-origin runbook define the boundary.

Partially implemented:

- Deployment profiles are descriptive and can be validated against operator-
  supplied runtime facts in the Python API. They do not provision PostgreSQL,
  queues, object storage, identity providers, keys, or failure domains.
- Docker verification is local inspection unless the user separately runs Docker build/runtime checks.
- Operational health reports DB schema, audit-chain status, and local job/error counts.
- Local real-TLS tests prove hostname verification, TLS 1.2/1.3 negotiation,
  SPA/API co-hosting, hostile Host rejection, asset 404 behavior, and security
  headers. An opt-in Chromium run executes the production bundle with zero CSP
  violations and confirms an identical API origin. No external proxy, public
  certificate lifecycle, assistive-technology interoperability, or
  internet-facing penetration evidence is claimed.

Roadmap:

- Compose smoke workflow.
- Runtime container checks before any stronger Docker claim.

Not supported:

- Hosted production deployment.
- Public internet hardening guarantee.
- Enterprise disaster-recovery guarantee.
