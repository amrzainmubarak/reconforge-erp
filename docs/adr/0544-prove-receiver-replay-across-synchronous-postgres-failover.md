# ADR 0544: Prove receiver replay across synchronous PostgreSQL failover

- Status: Accepted
- Date: 2026-08-22
- Scope: E-830 bounded receiver failure and failover conformance

## Context

E-829 proves that one PostgreSQL node serializes duplicate receiver requests,
survives process response loss, and restores its immutable history. That does
not prove the receiver history remains usable when the primary is fenced and a
physical standby is promoted. Client timeouts are also insufficient evidence:
an interrupted synchronous COMMIT may already be locally committed while the
caller has no response.

The repository already has a general single-host synchronous-standby HA drill,
but it does not exercise the write-back receiver contract or distinguish an
acknowledged remote-applied effect from an unacknowledged partitioned effect.

## Decision

Retain a dedicated two-version receiver failover matrix. Each PostgreSQL 16.14
and 17.10 cell creates two volume-backed nodes on separate control and
replication networks, configures physical streaming with
`synchronous_commit=remote_apply`, and runs the same digest-only receiver
contract under a non-privileged application role.

The acknowledged case commits on the primary and returns inside a child
process, but deliberately delivers no response to the caller. The standby must
already expose the immutable receipt/effect before failure. The partition case
disconnects replication, starts a second mutation, observes its backend in the
PostgreSQL `SyncRep` COMMIT wait, and terminates the client without assigning a
success or failure business outcome.

The controller must then:

1. verify and stop the exact primary container;
2. remove it before promotion, preventing the tested split-brain path;
3. promote the standby and replay the acknowledged identity without a new
   effect;
4. pause new mutations while the former primary volume is re-seeded;
5. restore synchronous remote-apply before retrying the uncertain identity;
6. let the database identity contract apply that identity exactly once;
7. prove both nodes have the same canonical history; and
8. restart the promoted primary, rediscover its dynamic endpoint, and replay
   both identities without changing counts or history.

Run the identical topology against the exact supply-chain-policy PostgreSQL
16.14 and 17.10 image digests and compare both final histories with a SQLite
reference built from the same two requests.

## Failure semantics

Only a response returned after synchronous remote apply is classified as an
acknowledged effect. A disconnected client waiting in `SyncRep` is
**uncertain**, not failed and not successful. The caller must resolve that
identity against the promoted receiver; it must never issue a different
idempotency key merely because the connection disappeared.

The local RTO measurement begins before fencing and ends after the promoted
receiver returns the exact acknowledged replay. A 60-second ceiling is a drill
gate for this named environment, not a production SLO. Acknowledged-effect RPO
is measured as zero transactions inside this synchronous single-host topology.

## Security and financial integrity

Credentials and payload bodies are never retained in the report. Runtime
credentials are generated per disposable topology. Application-role privilege
flags are all false. Data SQL remains parameterized, progress output contains
only fixed stage names, and every Docker resource carries an exact drill label
checked during cleanup.

No new financial amount, ledger posting, approval, or AI authority is added.
The proof covers synthetic digest-only effects and immutable evidence identity.

## Compatibility

The receiver implementations, product schemas, migrations, public APIs,
connector manifests, Community operation, and disabled-by-default write-back
policy are unchanged. This slice adds only a verification topology, closed
report/schema/tests, workflow definition, and documentation.

## Limitations

Both nodes still share one Docker Desktop host and one real failure domain.
Promotion, fencing, endpoint discovery, and rejoin are controlled manually by
the runner. There is no quorum, witness, automatic failover, cross-host loss,
zone/region partition, live provider, accounting posting, settlement, or
production assurance. Host-port reassignment observed after restart is a local
Docker runtime behavior, not a general PostgreSQL endpoint contract.

## Rollback

Remove the additive runner, report, schema, tests, CI artifact definition, ADR,
and execution records. Preserve any failed topology evidence. Never rewrite an
uncertain request as failed or allocate a new idempotency key without first
querying the promoted receiver identity.
