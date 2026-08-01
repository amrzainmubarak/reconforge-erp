from pathlib import Path


def test_reliability_runbook_covers_all_policy_ids_and_safe_recovery() -> None:
    text = Path("docs/operations/enterprise-reliability.md").read_text(encoding="utf-8")
    for required in (
        "RF-OPS-001", "RF-OPS-002", "RF-OPS-003", "RF-OPS-004", "RF-OPS-005",
        "no_data", "tenant", "raw financial rows", "synthetic", "not HA",
    ):
        assert required in text
