from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import jsonschema
import pytest

from reconforge.reliability.ha_dr import (
    HaDrCluster,
    HaDrError,
    HaDrNode,
    HaDrTopology,
    build_quorum_simulation_report,
    verify_quorum_simulation_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _topology() -> HaDrTopology:
    return HaDrTopology(
        cluster_id="cluster-test",
        nodes=(
            HaDrNode("node-a", "zone-a", 30),
            HaDrNode("node-b", "zone-b", 20),
            HaDrNode("node-c", "zone-c", 10),
            HaDrNode("witness-a", "zone-w", 0, "witness"),
        ),
    )


def test_topology_requires_independent_voters_and_witness() -> None:
    with pytest.raises(ValueError, match="failure domains"):
        HaDrTopology(
            cluster_id="cluster-test",
            nodes=(
                HaDrNode("node-a", "zone-a", 30),
                HaDrNode("node-b", "zone-a", 20),
                HaDrNode("node-c", "zone-b", 10),
                HaDrNode("witness-a", "zone-w", 0, "witness"),
            ),
        )
    with pytest.raises(ValueError, match="witness"):
        HaDrTopology(
            cluster_id="cluster-test",
            nodes=(
                HaDrNode("node-a", "zone-a", 30),
                HaDrNode("node-b", "zone-b", 20),
                HaDrNode("node-c", "zone-c", 10),
            ),
        )


def test_failover_requires_witness_quorum_and_fences_old_leader() -> None:
    cluster = HaDrCluster(_topology(), leader_id="node-a")
    cluster.commit(actor_id="node-a", payload="tx-1")
    with pytest.raises(HaDrError, match="witness_ack_required"):
        cluster.failover(
            failed_leader_id="node-a", healthy_voter_ids=("node-b", "node-c"), witness_ack=False, detection_tick=1
        )
    assert cluster.leader_id == "node-a"
    assert cluster.failover(
        failed_leader_id="node-a", healthy_voter_ids=("node-b", "node-c"), witness_ack=True, detection_tick=2
    ) == "node-b"
    assert cluster.fenced_nodes == {"node-a"}
    with pytest.raises(HaDrError, match="stale_leader_fenced"):
        cluster.commit(actor_id="node-a", payload="stale")


def test_election_is_stable_under_node_input_order() -> None:
    first = HaDrCluster(_topology(), leader_id="node-a")
    second = HaDrCluster(HaDrTopology("cluster-test", tuple(reversed(_topology().nodes))), leader_id="node-a")
    assert first.failover(
        failed_leader_id="node-a", healthy_voter_ids=("node-c", "node-b"), witness_ack=True, detection_tick=1
    ) == second.failover(
        failed_leader_id="node-a", healthy_voter_ids=("node-b", "node-c"), witness_ack=True, detection_tick=1
    )
    assert first.report() == second.report()


def test_quorum_simulation_report_is_schema_valid_digest_bound_and_limited() -> None:
    report = build_quorum_simulation_report()
    verify_quorum_simulation_report(report)
    schema = json.loads((ROOT / "docs/schemas/ha_dr_quorum_simulation.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(report)
    assert report["status"] == "simulation_only"
    assert report["topology"]["failure_domain_count"] == 3
    assert report["observed"]["committed_sequences"] == [1, 2, 3, 4]
    assert "container_domains_are_not_host_failure_domains" in report["limitations"]
    tampered = json.loads(json.dumps(report))
    tampered["observed"]["rpo_transactions"] = 1
    with pytest.raises(ValueError):
        verify_quorum_simulation_report(tampered)


def test_quorum_report_script_writes_verifiable_artifact(tmp_path: Path) -> None:
    path = ROOT / ".github/scripts/verify_ha_dr_quorum_simulation.py"
    spec = spec_from_file_location("verify_ha_dr_quorum_simulation", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "ha-dr.json"
    # Exercise the same callable used by the CLI without mutating the repository artifact.
    report = module.build_quorum_simulation_report()
    module.verify_quorum_simulation_report(report)
    output.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8"))["report_digest"] == report["report_digest"]
