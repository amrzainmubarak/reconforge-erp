# HA/DR quorum and fencing simulation

`postgres-multi-domain-quorum-simulation-v1` is a deterministic safety
contract, not a deployment. It models:

- three voter nodes in three distinct failure domains;
- one witness and a two-vote quorum;
- monotonic terms and detection ticks;
- fence-before-elect ordering;
- stable priority/ID election;
- exact catch-up before standby repromotion;
- stale-leader commit refusal and digest-bound event evidence.

Run it locally:

```text
python .github/scripts/verify_ha_dr_quorum_simulation.py \
  --output docs/execution/HA_DR_QUORUM_SIMULATION_2026-08-04.json
```

The report must remain `status: simulation_only`. It is useful for validating
PostgreSQL, queue, and object-store adapters, but it does not prove that
containers are independent hosts, that an external fencing device exists, or
that failover happens within a wall-clock SLO. The existing
`verify_postgres_ha_dr.py` drill remains the authoritative single-host runtime
exercise until independent hosts and a witness-backed controller are supplied.
