# ADR 0662: Add a bounded Community Docker Compose profile

- Status: Accepted
- Date: 2026-08-26
- Owners: Platform / DevSecOps

## Context

The standalone Docker image had a hardened, documented smoke contract, but
there was no current Compose artifact for a local operator to start the
Community API. The API can initialize and serve its local SQLite database
without PostgreSQL, Redis, hosted identity, object storage, or network
egress. A Compose profile can therefore reduce local setup friction if its
scope is kept explicit.

## Decision

Ship `compose.yaml` as a Community/local-only profile with these invariants:

- one ReconForge service and one named SQLite data volume;
- idempotent `reconforge db init` before `reconforge api serve`;
- loopback-only host publication on port `8765`;
- an internal Compose network, read-only root filesystem, non-root UID
  `10001`, dropped capabilities, `no-new-privileges`, and a constrained `/tmp`;
- a healthcheck against the local API health endpoint;
- no implicit PostgreSQL, Redis, object-storage, external identity, or hosted
  service dependency.

This does not establish Team, Enterprise, Regulated, HA/DR, backup/restore,
production availability, multi-user authorization, hosted provenance, or
compliance evidence. Those remain separate gates.

## Evidence

- `tests/test_compose_profile.py` validates the checked-in contract.
- `docker compose -f compose.yaml config --quiet` passed.
- The image built with `docker compose ... build --pull`.
- A live one-off Compose service reached `healthy`; its internal health
  response reported SQLite reachable at schema `45/45`, UID `10001`, and an
  existing `/data/reconforge.db`.
- After restart, the service returned to `healthy` and the database remained
  present. The environment reserved host port `8765`; a temporary host-port
  mapping was also not reachable through the local Docker Desktop proxy, so
  host-port reachability is recorded as an environment limitation, not as
  positive evidence. The container healthcheck and in-container HTTP request
  are the runtime evidence for this slice.

## Consequences and rollback

The repository now has a repeatable local start path with persistent local
state. Operators must still protect the named volume and must not expose the
port beyond loopback without adding authentication and an explicit deployment
review. Rollback is a revert of `compose.yaml`, the Docker `/data` directory
creation, this ADR, tests, and the synchronized documentation/execution
entries; the standalone image contract remains independently usable.
