import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_docker_ha_dr_report_is_closed_measured_and_cannot_claim_host_loss() -> None:
    schema = json.loads((ROOT / "docs/schemas/ha_dr_drill_report.schema.json").read_text(encoding="utf-8"))
    report = json.loads((ROOT / "docs/execution/HA_DR_DOCKER_DRILL_2026-07-30.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    assert report["measurement"]["rpo_transactions"] <= report["measurement"]["rpo_ceiling_transactions"]
    assert report["measurement"]["rto_seconds"] <= report["measurement"]["rto_ceiling_seconds"]
    assert report["measurement"]["failback_rpo_transactions"] == 0
    assert report["measurement"]["failback_rto_seconds"] <= report["measurement"]["rto_ceiling_seconds"]
    assert report["fencing"]["verified_absent_before_promotion"] is True
    assert report["fencing"]["failback_verified_absent_before_promotion"] is True
    assert report["backup_restore"]["digest_matches"] is True
    assert report["integrity"]["partition_write_not_acknowledged"] is True
    assert report["integrity"]["former_primary_rejoined_read_only"] is True
    assert report["integrity"]["post_failback_sequence"] == 4
    assert report["infrastructure"]["failure_domains"] == 1
    assert "single_host_not_host_loss" in report["limitations"]
    assert "no_enterprise_ready_claim" in report["limitations"]


def test_recorded_primary_identity_is_hashed_not_a_reusable_container_identifier() -> None:
    report = json.loads((ROOT / "docs/execution/HA_DR_DOCKER_DRILL_2026-07-30.json").read_text(encoding="utf-8"))
    recorded = {
        report["fencing"]["old_primary_id_sha256"],
        report["fencing"]["failback_old_primary_id_sha256"],
    }
    assert all(len(value) == 64 for value in recorded)
    assert hashlib.sha256(b"").hexdigest() not in recorded
