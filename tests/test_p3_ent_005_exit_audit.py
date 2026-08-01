from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import yaml

from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS

ROOT = Path(__file__).resolve().parents[1]


def _yaml(relative: str) -> dict[str, Any]:
    value = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def test_p3_ent_005_exit_audit_has_complete_evidence_and_claim_boundaries() -> None:
    audit = _yaml("docs/execution/P3_ENT_005_EXIT_AUDIT.yaml")
    assert audit["task_id"] == "P3-ENT-005"
    assert audit["audit_id"] == "E-189"
    assert audit["status"] == "verified"
    assert audit["migration_head"] == "0048_postgres_notifications"
    assert audit["migration_head"] in POSTGRES_MIGRATION_REVISIONS
    assert POSTGRES_MIGRATION_REVISIONS.index(audit["migration_head"]) < len(POSTGRES_MIGRATION_REVISIONS) - 1
    assert {gate["id"] for gate in audit["gates"]} == {
        "timezone_semantics",
        "misfire_policy",
        "hosted_polling_runtime",
        "atomic_idempotent_dispatch_and_notification_enqueue",
        "forced_rls_route_and_subscription_scope",
        "default_deny_egress_and_ssrf_controls",
        "closed_redacted_payload",
        "retry_dead_letter_replay_and_append_only_audit",
        "migration_and_recovery",
    }
    assert all(gate["status"] == "verified" and gate["evidence"] for gate in audit["gates"])
    assert all((ROOT / item).is_file() for gate in audit["gates"] for item in gate["evidence"])
    assert {
        "at_least_once_delivery_receiver_idempotency_required",
        "no_external_provider_interoperability_evidence",
        "no_ha_or_dr_claim",
        "no_compliance_or_certification_claim",
        "no_external_penetration_or_assurance_claim",
        "no_enterprise_ready_claim",
    }.issubset(audit["limitations"])
    assert not any(audit["publication"].values())

    runtime = audit["runtime_evidence"]
    assert runtime["focused_live_result"] == "50_passed"
    assert runtime["focused_live_skips"] == 0
    assert runtime["fresh_migration"] == "0001_to_0048_passed"
    assert runtime["direct_empty_rollback"] == "0048_to_0047_to_0048_passed"
    assert runtime["nonempty_rollback"] == "refused_before_mutation_head_and_evidence_preserved"
    assert runtime["external_messages_sent"] == 0
    assert runtime["full_live_regression_duration_seconds"] > 0
    assert runtime["live_policy_count"] == runtime["live_rls_table_count"] == runtime[
        "live_forced_rls_table_count"
    ]


def test_p3_ent_005_failure_matrix_names_real_tests_and_covers_required_surfaces() -> None:
    audit = _yaml("docs/execution/P3_ENT_005_EXIT_AUDIT.yaml")
    all_tests: set[str] = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        all_tests.update(_test_functions(path))
    entries = audit["failure_matrix"]
    assert len(entries) == 14
    assert all(entry["evidence_test"] in all_tests for entry in entries)
    threats = {entry["threat"] for entry in entries}
    assert any("schedule" in threat or "misfire" in threat for threat in threats)
    assert any("egress" in threat or "webhook" in threat or "email" in threat for threat in threats)
    assert any("sibling" in threat for threat in threats)
    assert any("evidence" in threat for threat in threats)
    assert all(entry["result"] not in {"allowed", "unknown", "planned"} for entry in entries)
