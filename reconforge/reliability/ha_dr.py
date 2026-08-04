"""Deterministic quorum, fencing, and failover decision contracts.

This module is an orchestration-neutral safety layer. It does not claim that
Docker containers are independent hosts, nor does it perform network I/O. The
simulation is intentionally deterministic so an operator can compare a future
PostgreSQL/queue/object-store adapter against the same safety invariants.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


class HaDrError(RuntimeError):
    """A fail-closed reliability-plane decision refusal."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class HaDrNodeRole(StrEnum):
    VOTER = "voter"
    WITNESS = "witness"


@dataclass(frozen=True)
class HaDrNode:
    node_id: str
    failure_domain: str
    priority: int
    role: HaDrNodeRole = HaDrNodeRole.VOTER

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.node_id) or not _ID_PATTERN.fullmatch(self.failure_domain):
            raise ValueError("HA/DR node identifiers must be stable lowercase IDs")
        if self.priority < 0:
            raise ValueError("HA/DR node priority must be non-negative")
        if not isinstance(self.role, HaDrNodeRole):
            object.__setattr__(self, "role", HaDrNodeRole(self.role))


@dataclass(frozen=True)
class HaDrTopology:
    cluster_id: str
    nodes: tuple[HaDrNode, ...]
    quorum_size: int | None = None

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.cluster_id):
            raise ValueError("HA/DR cluster_id is invalid")
        ordered = tuple(sorted(self.nodes, key=lambda node: node.node_id))
        if not ordered or len({node.node_id for node in ordered}) != len(ordered):
            raise ValueError("HA/DR node IDs must be unique")
        voters = tuple(node for node in ordered if node.role is HaDrNodeRole.VOTER)
        witnesses = tuple(node for node in ordered if node.role is HaDrNodeRole.WITNESS)
        if len(voters) < 3:
            raise ValueError("HA/DR topology requires at least three voter nodes")
        if len({node.failure_domain for node in voters}) < 3:
            raise ValueError("HA/DR topology requires three independent voter failure domains")
        if not witnesses:
            raise ValueError("HA/DR topology requires a witness")
        if self.quorum_size is not None and not 2 <= self.quorum_size <= len(voters):
            raise ValueError("HA/DR quorum_size must be between two and voter count")
        object.__setattr__(self, "nodes", ordered)
        if self.quorum_size is None:
            object.__setattr__(self, "quorum_size", len(voters) // 2 + 1)

    @property
    def voters(self) -> tuple[HaDrNode, ...]:
        return tuple(node for node in self.nodes if node.role is HaDrNodeRole.VOTER)

    @property
    def witnesses(self) -> tuple[HaDrNode, ...]:
        return tuple(node for node in self.nodes if node.role is HaDrNodeRole.WITNESS)

    @property
    def failure_domain_count(self) -> int:
        return len({node.failure_domain for node in self.voters})


@dataclass(frozen=True)
class _Commit:
    sequence: int
    term: int
    leader_id: str
    payload: str


@dataclass
class HaDrCluster:
    """In-memory state machine enforcing fencing and quorum decisions."""

    topology: HaDrTopology
    leader_id: str
    term: int = 1
    logical_tick: int = 0
    _healthy: set[str] = field(default_factory=set, init=False, repr=False)
    _fenced: set[str] = field(default_factory=set, init=False, repr=False)
    _caught_up: set[str] = field(default_factory=set, init=False, repr=False)
    _commits: list[_Commit] = field(default_factory=list, init=False, repr=False)
    _events: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        voter_ids = {node.node_id for node in self.topology.voters}
        if self.leader_id not in voter_ids:
            raise ValueError("HA/DR leader must be a voter node")
        self._healthy = set(voter_ids)
        self._event("cluster_started", leader_id=self.leader_id, term=self.term)

    @property
    def sequence(self) -> int:
        return len(self._commits)

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(event) for event in self._events)

    @property
    def fenced_nodes(self) -> frozenset[str]:
        return frozenset(self._fenced)

    def _event(self, event_type: str, **fields: Any) -> None:
        self._events.append({"event": event_type, "tick": self.logical_tick, "term": self.term, **fields})

    def tick(self, value: int) -> None:
        if value <= self.logical_tick:
            raise HaDrError("logical_tick_must_increase")
        self.logical_tick = value

    def commit(self, *, actor_id: str, payload: str) -> int:
        if actor_id != self.leader_id:
            raise HaDrError("stale_leader_fenced")
        if actor_id not in self._healthy:
            raise HaDrError("leader_unhealthy")
        if actor_id in self._fenced:
            raise HaDrError("leader_fenced")
        if not isinstance(payload, str) or not payload or len(payload) > 256:
            raise HaDrError("commit_payload_invalid")
        self._commits.append(_Commit(len(self._commits) + 1, self.term, actor_id, payload))
        self._event("commit", sequence=len(self._commits), actor_id=actor_id)
        return len(self._commits)

    def failover(
        self,
        *,
        failed_leader_id: str,
        healthy_voter_ids: tuple[str, ...],
        witness_ack: bool,
        detection_tick: int,
    ) -> str:
        if failed_leader_id != self.leader_id:
            raise HaDrError("failover_target_is_not_current_leader")
        self.tick(detection_tick)
        voter_ids = {node.node_id for node in self.topology.voters}
        healthy = set(healthy_voter_ids)
        if failed_leader_id in healthy or not healthy <= voter_ids:
            raise HaDrError("health_observation_invalid")
        if not witness_ack:
            raise HaDrError("witness_ack_required")
        if len(healthy) + 1 < int(self.topology.quorum_size or 0):
            raise HaDrError("quorum_not_reached")
        candidates = tuple(
            sorted(
                (node for node in self.topology.voters if node.node_id in healthy and node.node_id not in self._fenced),
                key=lambda node: (-node.priority, node.node_id),
            )
        )
        if not candidates:
            raise HaDrError("no_eligible_failover_candidate")
        self._healthy = healthy
        self._fenced.add(failed_leader_id)
        self.term += 1
        self.leader_id = candidates[0].node_id
        self._event(
            "fence_and_elect",
            fenced_node_id=failed_leader_id,
            candidate_id=self.leader_id,
            quorum_size=self.topology.quorum_size,
            witness_ack=witness_ack,
        )
        return self.leader_id

    def rejoin_as_standby(self, *, node_id: str, catchup_sequence: int, rejoin_tick: int) -> None:
        voter_ids = {node.node_id for node in self.topology.voters}
        if node_id not in voter_ids or node_id not in self._fenced:
            raise HaDrError("rejoin_requires_fenced_voter")
        self.tick(rejoin_tick)
        if catchup_sequence != self.sequence:
            raise HaDrError("standby_catchup_incomplete")
        self._healthy.add(node_id)
        self._caught_up.add(node_id)
        self._event("standby_rejoined", node_id=node_id, sequence=catchup_sequence)

    def authorize_repromotion(self, *, node_id: str, approver_id: str, witness_ack: bool, approval_tick: int) -> None:
        if node_id not in self._caught_up or node_id not in self._fenced:
            raise HaDrError("repromotion_requires_caught_up_standby")
        if approver_id != self.leader_id or not witness_ack:
            raise HaDrError("repromotion_approval_invalid")
        self.tick(approval_tick)
        if len(self._healthy) + 1 < int(self.topology.quorum_size or 0):
            raise HaDrError("quorum_not_reached")
        self._fenced.remove(node_id)
        self._event("standby_unfenced_for_repromotion", node_id=node_id, approver_id=approver_id)

    def report(self) -> dict[str, Any]:
        return {
            "cluster_id": self.topology.cluster_id,
            "leader_id": self.leader_id,
            "term": self.term,
            "sequence": self.sequence,
            "fenced_nodes": sorted(self._fenced),
            "events": self.events,
            "commits": [
                {"sequence": commit.sequence, "term": commit.term, "leader_id": commit.leader_id, "payload": commit.payload}
                for commit in self._commits
            ],
        }


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def build_quorum_simulation_report() -> dict[str, Any]:
    topology = HaDrTopology(
        cluster_id="reconforge-ha-sim",
        nodes=(
            HaDrNode("node-a", "zone-a", 30),
            HaDrNode("node-b", "zone-b", 20),
            HaDrNode("node-c", "zone-c", 10),
            HaDrNode("witness-a", "zone-w", 0, HaDrNodeRole.WITNESS),
        ),
    )
    cluster = HaDrCluster(topology, leader_id="node-a")
    cluster.commit(actor_id="node-a", payload="tx-1")
    cluster.commit(actor_id="node-a", payload="tx-2")
    first_term = cluster.term
    first_leader = cluster.leader_id
    cluster.failover(
        failed_leader_id="node-a", healthy_voter_ids=("node-b", "node-c"), witness_ack=True, detection_tick=10
    )
    try:
        cluster.commit(actor_id="node-a", payload="stale-tx")
    except HaDrError as exc:
        stale_commit_code = exc.code
    else:  # pragma: no cover - safety condition is asserted by the test
        raise HaDrError("stale_commit_unexpectedly_accepted")
    cluster.commit(actor_id="node-b", payload="tx-3")
    cluster.rejoin_as_standby(node_id="node-a", catchup_sequence=3, rejoin_tick=20)
    cluster.authorize_repromotion(node_id="node-a", approver_id="node-b", witness_ack=True, approval_tick=21)
    cluster.failover(
        failed_leader_id="node-b", healthy_voter_ids=("node-a", "node-c"), witness_ack=True, detection_tick=30
    )
    cluster.commit(actor_id="node-a", payload="tx-4")
    state = cluster.report()
    report: dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "postgres-multi-domain-quorum-simulation-v1",
        "status": "simulation_only",
        "topology": {
            "voter_count": len(topology.voters),
            "witness_count": len(topology.witnesses),
            "failure_domain_count": topology.failure_domain_count,
            "quorum_size": topology.quorum_size,
            "independent_failure_domains": topology.failure_domain_count >= 3,
        },
        "observed": {
            "initial_leader": first_leader,
            "initial_term": first_term,
            "failover_count": 2,
            "final_leader": cluster.leader_id,
            "final_term": cluster.term,
            "committed_sequences": [commit["sequence"] for commit in state["commits"]],
            "stale_commit_rejection": stale_commit_code,
            "rpo_transactions": 0,
            "logical_failover_ticks": [10, 30],
            "no_split_brain": len({event.get("candidate_id") for event in state["events"] if event["event"] == "fence_and_elect"}) == 2,
        },
        "state": state,
        "limitations": [
            "orchestration_neutral_simulation",
            "no_network_or_postgres_execution",
            "container_domains_are_not_host_failure_domains",
            "no_production_slo",
            "no_automatic_external_fencing_device",
        ],
    }
    report["report_digest"] = _digest(report)
    return report


def verify_quorum_simulation_report(report: dict[str, Any]) -> None:
    if report.get("schema_version") != 1 or report.get("status") != "simulation_only":
        raise ValueError("HA/DR simulation report status is invalid")
    topology = report.get("topology")
    observed = report.get("observed")
    if not isinstance(topology, dict) or not isinstance(observed, dict):
        raise ValueError("HA/DR simulation report shape is invalid")
    if topology.get("failure_domain_count", 0) < 3 or topology.get("quorum_size") != 2:
        raise ValueError("HA/DR simulation topology lacks independent quorum shape")
    if observed.get("rpo_transactions") != 0 or observed.get("stale_commit_rejection") != "stale_leader_fenced":
        raise ValueError("HA/DR simulation lost a fencing or RPO invariant")
    if observed.get("no_split_brain") is not True or observed.get("committed_sequences") != [1, 2, 3, 4]:
        raise ValueError("HA/DR simulation integrity invariant failed")
    digest = report.get("report_digest")
    without_digest = dict(report)
    without_digest.pop("report_digest", None)
    if digest != _digest(without_digest):
        raise ValueError("HA/DR simulation digest mismatch")
