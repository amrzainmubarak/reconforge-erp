from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PARITY = ROOT / "docs/execution/POSTGRES_PARITY_INVENTORY.yaml"
BOUNDARIES = ROOT / "docs/execution/REPOSITORY_BOUNDARY_INVENTORY.yaml"


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_postgres_parity_inventory_covers_every_application_service_exactly() -> None:
    parity = _load(PARITY)
    boundaries = _load(BOUNDARIES)
    expected = {(row["file"], row["service"]) for row in boundaries["application_services"]}
    actual = {(row["file"], row["service"]) for row in parity["boundaries"]}
    assert actual == expected
    assert len(actual) == parity["summary"]["total"]


def test_postgres_parity_status_evidence_and_counts_are_consistent() -> None:
    parity = _load(PARITY)
    allowed = set(parity["allowed_statuses"])
    counts = {status: 0 for status in allowed}
    for row in parity["boundaries"]:
        status = row["status"]
        assert status in allowed
        counts[status] += 1
        if status in {"live_verified_current", "live_test_available", "contract_only"}:
            module_name, class_name = row["adapter"].rsplit(".", 1)
            assert hasattr(importlib.import_module(module_name), class_name)
            assert (ROOT / row["test"]).is_file()
        if status == "absent":
            assert row["risk"]
            assert "adapter" not in row
        if status == "not_applicable":
            assert row["reason"]
    for status in allowed:
        assert counts[status] == parity["summary"][status]


def test_current_live_claim_requires_an_unskipped_recorded_gate() -> None:
    parity = _load(PARITY)
    gate = parity["current_live_gate"]
    live_boundaries = [row for row in parity["boundaries"] if row["status"] == "live_test_available"]
    assert gate["application_and_migration_result"] == "passed"
    assert gate["native_encrypted_backup_restore_result"] == "passed"
    assert gate["covered_live_boundaries"] == len(live_boundaries) == 25
    assert gate["skipped_live_boundaries"] == 0
    assert gate["database_image_digest"].startswith("sha256:")
    assert "non_superuser" in gate["application_role"]
