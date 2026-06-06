# Deployment Boundaries

Implemented:

- API and Studio default to localhost binding.
- `reconforge deployment release-check` performs a local DB migration smoke check and output directory write check.
- `reconforge deployment docker-verify` checks local Docker file/tooling presence.

Partially implemented:

- Docker verification is local inspection unless the user separately runs Docker build/runtime checks.
- Operational health reports DB schema, audit-chain status, and local job/error counts.

Roadmap:

- Compose smoke workflow.
- Runtime container checks before any stronger Docker claim.

Not supported:

- Hosted production deployment.
- Public internet hardening guarantee.
- Enterprise disaster-recovery guarantee.
