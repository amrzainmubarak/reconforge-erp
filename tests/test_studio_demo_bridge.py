from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.enterprise_demo import SYNTHETIC_DATA_MARKER
from reconforge.studio.demo_bridge import (
    MAX_SOURCE_FILE_BYTES,
    STUDIO_EVIDENCE_BINDER_FILENAME,
    STUDIO_EXCEPTION_QUEUE_FILENAME,
    STUDIO_INVENTORY_CONTROL_FILENAME,
    StudioDemoBridgeError,
    build_studio_demo_bundle,
    build_studio_demo_data,
)

runner = CliRunner()


def _payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "synthetic_data_only": True,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        "generated_at": "2026-06-01T09:00:00Z",
        "records": records,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_demo_package(path: Path) -> None:
    _write_json(
        path / "demo_manifest.json",
        {
            "synthetic_data_only": True,
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
            "generated_at": "2026-06-01T09:00:00Z",
            "local_first": True,
            "external_calls": False,
        },
    )
    _write_json(
        path / "sample_entities.json",
        _payload(
            [
                {
                    "entity_code": "SYN-01",
                    "entity_name": "Synthetic Operations",
                    "region": "EMEA",
                    "currency": "USD",
                    "private_note": "must not cross the bridge",
                },
            ],
        ),
    )
    _write_json(
        path / "sample_periods.json",
        _payload(
            [
                {
                    "period_name": "2026-05",
                    "start_date": "2026-05-01",
                    "end_date": "2026-05-31",
                    "status": "Synthetic current period",
                },
            ],
        ),
    )
    _write_json(
        path / "sample_close_tasks.json",
        _payload(
            [
                {
                    "task_id": "CLOSE-SYN-001",
                    "period_name": "2026-05",
                    "name": "Review synthetic exceptions",
                    "status": "In Progress",
                    "owner": "Synthetic Reviewer",
                },
            ],
        ),
    )
    _write_json(
        path / "reports" / "dashboard_metrics.json",
        _payload(
            [
                {"metric_key": "close_completion", "value": 64.0, "lineage": "Synthetic close tasks."},
                {"metric_key": "evidence_coverage", "value": 91.0, "lineage": "Synthetic evidence registry."},
                {
                    "metric_key": "unresolved_high_risk_exceptions",
                    "value": 2.0,
                    "lineage": "Synthetic exception queue.",
                },
                {"metric_key": "match_rate", "value": 75.0, "lineage": "Synthetic match results."},
            ],
        ),
    )
    _write_json(
        path / "reports" / "unified_exceptions.json",
        _payload(
            [
                {
                    "source_type": "journal",
                    "period_name": "2026-05",
                    "entity_code": "SYN-01",
                    "account_code": "9999",
                    "control_code": "JRN-SYN",
                    "risk_rating": "high",
                    "owner": "Synthetic Reviewer",
                    "status": "Open",
                    "description": "Synthetic high-value journal requires review.",
                    "raw_sensitive_record": "must not cross the bridge",
                },
                {
                    "source_type": "matching",
                    "period_name": "2026-05",
                    "entity_code": "SYN-01",
                    "risk_rating": "medium",
                    "status": "In Review",
                    "description": "Synthetic matching exception.",
                },
            ],
        ),
    )
    _write_json(
        path / "reports" / "evidence_registry.json",
        _payload(
            [
                {
                    "evidence_code": "EVD-SYN-001",
                    "provenance_type": "synthetic-local-file",
                    "redaction_status": "synthetic",
                    "evidence_status": "Registered",
                    "checksum_sha256": "a" * 64,
                    "source_path": "must not cross the bridge",
                },
            ],
        ),
    )
    _write_json(
        path / "sample_inventory_control.json",
        _payload(
            [
                {
                    "record_type": "on_hand",
                    "item_code": "SYN-PART-01",
                    "item_name": "Synthetic service part",
                    "uom_code": "EA",
                    "warehouse_code": "SYN-MAIN",
                    "warehouse_name": "Synthetic main store",
                    "location_code": "STOCK",
                    "entity_code": "SYN-01",
                    "lot_serial_code": "LOT-SYN-01",
                    "tracking_type": "Lot",
                    "quantity": "12.500",
                    "private_cost": "must not cross the bridge",
                },
                {
                    "record_type": "movement",
                    "movement_number": "RCV/SYN/001",
                    "movement_type": "Receipt",
                    "status": "Posted",
                    "movement_date": "2026-05-10",
                    "entity_code": "SYN-01",
                    "from_location": "",
                    "to_location": "SYN-MAIN/STOCK",
                    "line_count": 1,
                    "quantity": "12.500",
                },
                {
                    "record_type": "exception",
                    "control_code": "INV-MISSING-ACCOUNT",
                    "risk_rating": "medium",
                    "item_code": "SYN-PART-01",
                    "location": "",
                    "quantity": "",
                    "description": "Synthetic stock item needs a local account reference.",
                },
                {
                    "record_type": "count",
                    "count_number": "COUNT/SYN/001",
                    "status": "Approved",
                    "count_date": "2026-05-20",
                    "entity_code": "SYN-01",
                    "warehouse_code": "SYN-MAIN",
                    "location_code": "STOCK",
                    "line_count": 1,
                    "counted_line_count": 1,
                    "variance_line_count": 1,
                    "adjustment_movement_number": "ADJ/SYN/002",
                },
                {
                    "record_type": "reorder_signal",
                    "risk_rating": "medium",
                    "item_code": "SYN-PART-01",
                    "item_name": "Synthetic service part",
                    "uom_code": "EA",
                    "warehouse_code": "SYN-MAIN",
                    "location_code": "STOCK",
                    "on_hand_quantity": "12.500",
                    "minimum_quantity": "15.000",
                    "target_quantity": "25.000",
                    "suggested_quantity": "12.500",
                    "lead_time_days": 5,
                },
                {
                    "record_type": "valuation",
                    "valuation_number": "VAL/SYN/001",
                    "movement_number": "RCV/SYN/001",
                    "movement_type": "Receipt",
                    "status": "Approved",
                    "valuation_date": "2026-05-10",
                    "entity_code": "SYN-01",
                    "costing_method": "FIFO",
                    "currency_code": "USD",
                    "total_value": "1250.00",
                    "finance_entry_number": "IV-VAL/SYN/001",
                    "finance_entry_status": "Draft",
                    "private_rate": "must not cross the bridge",
                },
                {
                    "record_type": "valuation",
                    "valuation_number": "VAL/SYN/002",
                    "movement_number": "DLV/SYN/002",
                    "movement_type": "Delivery",
                    "status": "Approved",
                    "valuation_date": "2026-05-11",
                    "entity_code": "SYN-01",
                    "costing_method": "FIFO",
                    "currency_code": "USD",
                    "total_value": "300.00",
                    "finance_entry_number": "IV-VAL/SYN/002",
                    "finance_entry_status": "Draft",
                },
                {
                    "record_type": "valuation_reversal",
                    "reversal_number": "IVR/SYN/001",
                    "original_valuation_number": "VAL/SYN/002",
                    "reversal_movement_number": "REV/DLV/SYN/002",
                    "original_movement_type": "Delivery",
                    "reversal_movement_type": "Receipt",
                    "status": "Approved",
                    "reversal_date": "2026-05-12",
                    "entity_code": "SYN-01",
                    "currency_code": "USD",
                    "total_value": "300.00",
                    "layer_effect": "Restore",
                    "layer_effect_count": 1,
                    "finance_entry_number": "IVR-IVR/SYN/001",
                    "finance_entry_status": "Draft",
                    "private_rate": "must not cross the bridge",
                },
                {
                    "record_type": "cost_layer",
                    "layer_id": "SYN-LAYER-001",
                    "valuation_number": "VAL/SYN/001",
                    "item_code": "SYN-PART-01",
                    "item_name": "Synthetic service part",
                    "uom_code": "EA",
                    "lot_serial_code": "LOT-SYN-01",
                    "entity_code": "SYN-01",
                    "currency_code": "USD",
                    "original_quantity": "12.500",
                    "remaining_quantity": "9.500",
                    "original_value": "1250.00",
                    "remaining_value": "950.00",
                },
            ],
        ),
    )


def test_build_studio_demo_data_projects_versioned_synthetic_contract(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    output = tmp_path / "web" / "studio-overview.json"
    _write_demo_package(source)

    written = build_studio_demo_data(source, output)

    assert written == output.resolve()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["synthetic_data_only"] is True
    assert payload["source"] == {
        "kind": "reconforge-enterprise-demo",
        "local_first": True,
        "external_calls": False,
    }
    assert payload["workspace"] == {
        "name": "Finance Controls Workspace",
        "current_period": "2026-05",
        "entity_count": 1,
        "evidence_count": 1,
        "close_task_count": 1,
    }
    assert payload["executive_brief"] == {
        "readiness_score": 0.0,
        "readiness_status": "attention",
        "high_risk_count": 1,
        "open_exception_count": 2,
        "blocked_task_count": 0,
        "completed_task_count": 0,
    }
    assert payload["control_domains"] == [
        {
            "domain": "close",
            "score": 64.0,
            "status": "watch",
            "lineage": "Synthetic close tasks.",
        },
        {
            "domain": "evidence",
            "score": 91.0,
            "status": "strong",
            "lineage": "Synthetic evidence registry.",
        },
        {
            "domain": "matching",
            "score": 75.0,
            "status": "watch",
            "lineage": "Synthetic match results.",
        },
        {
            "domain": "controls",
            "score": 0.0,
            "status": "attention",
            "lineage": "Not available in this synthetic snapshot.",
        },
    ]
    assert payload["entity_health"] == [
        {
            "entity_code": "SYN-01",
            "entity_name": "Synthetic Operations",
            "region": "EMEA",
            "currency": "USD",
            "open_exception_count": 2,
            "high_risk_count": 1,
            "status": "watch",
        }
    ]
    assert payload["exceptions"][0]["risk_rating"] == "high"
    assert payload["risk_distribution"] == [
        {"count": 0, "risk": "critical"},
        {"count": 1, "risk": "high"},
        {"count": 1, "risk": "medium"},
        {"count": 0, "risk": "low"},
    ]
    serialized = json.dumps(payload)
    assert "raw_sensitive_record" not in serialized
    assert "private_note" not in serialized
    assert "source_path" not in serialized


def test_build_studio_demo_data_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    output = tmp_path / "studio-overview.json"
    _write_demo_package(source)

    build_studio_demo_data(source, output)
    first = output.read_bytes()
    build_studio_demo_data(source, output)

    assert output.read_bytes() == first


def test_build_studio_demo_bundle_writes_native_page_contracts(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    output = tmp_path / "web" / "studio-overview.json"
    _write_demo_package(source)

    bundle = build_studio_demo_bundle(source, output)

    assert bundle.overview_path == output.resolve()
    assert bundle.exception_queue_path.name == STUDIO_EXCEPTION_QUEUE_FILENAME
    assert bundle.evidence_binder_path.name == STUDIO_EVIDENCE_BINDER_FILENAME
    assert bundle.inventory_control_path.name == STUDIO_INVENTORY_CONTROL_FILENAME
    assert all(path.exists() for path in bundle.paths)

    overview = json.loads(bundle.overview_path.read_text(encoding="utf-8"))
    overview_schema = json.loads(
        (Path(__file__).resolve().parents[1] / "docs" / "schemas" / "studio_overview.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(overview_schema)
    Draft202012Validator(overview_schema).validate(overview)

    exceptions = json.loads(bundle.exception_queue_path.read_text(encoding="utf-8"))
    assert exceptions["schema_version"] == 1
    assert exceptions["summary"] == {
        "entity_count": 1,
        "high_risk": 1,
        "open": 1,
        "total": 2,
        "unassigned": 1,
    }
    assert exceptions["exceptions"][0]["exception_id"].startswith("SYN-EXC-")
    assert len(exceptions["exceptions"][0]["exception_id"]) == 20

    evidence = json.loads(bundle.evidence_binder_path.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == 1
    assert evidence["summary"] == {
        "available": 0,
        "checksum_count": 1,
        "coverage_percent": 91.0,
        "synthetic_redaction_count": 1,
        "total": 1,
    }
    assert evidence["evidence"][0]["checksum_sha256"] == "a" * 64
    assert "source_path" not in json.dumps(evidence)

    inventory = json.loads(bundle.inventory_control_path.read_text(encoding="utf-8"))
    inventory_schema = json.loads(
        (Path(__file__).resolve().parents[1] / "docs" / "schemas" / "studio_inventory_control.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(inventory_schema)
    Draft202012Validator(inventory_schema).validate(inventory)
    assert inventory["schema_version"] == 1
    assert inventory["summary"] == {
        "exception_count": 1,
        "count_session_count": 1,
        "item_count": 1,
        "location_count": 1,
        "movement_count": 1,
        "posted_movement_count": 1,
        "reorder_signal_count": 1,
        "valuation_document_count": 2,
        "valuation_reversal_count": 1,
        "open_cost_layer_count": 1,
        "finance_draft_count": 3,
        "warehouse_count": 1,
    }
    assert inventory["on_hand"][0]["quantity"] == "12.500"
    assert inventory["exceptions"][0]["exception_id"].startswith("SYN-INV-EXC-")
    assert inventory["count_sessions"][0]["status"] == "Approved"
    assert inventory["reorder_signals"][0]["suggested_quantity"] == "12.500"
    assert inventory["valuations"][0]["finance_entry_status"] == "Draft"
    assert inventory["valuation_reversals"][0]["layer_effect"] == "Restore"
    assert inventory["valuation_reversals"][0]["finance_entry_status"] == "Draft"
    assert inventory["cost_layers"][0]["remaining_value"] == "950.00"
    assert "private_cost" not in json.dumps(inventory)


def test_build_studio_demo_bundle_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    output = tmp_path / "studio-overview.json"
    _write_demo_package(source)

    first_bundle = build_studio_demo_bundle(source, output)
    first = {path.name: path.read_bytes() for path in first_bundle.paths}
    second_bundle = build_studio_demo_bundle(source, output)

    assert {path.name: path.read_bytes() for path in second_bundle.paths} == first


def test_build_studio_demo_bundle_keeps_older_packages_compatible(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    output = tmp_path / "studio-overview.json"
    _write_demo_package(source)
    (source / "sample_inventory_control.json").unlink()

    bundle = build_studio_demo_bundle(source, output)
    inventory = json.loads(bundle.inventory_control_path.read_text(encoding="utf-8"))

    assert inventory["summary"]["item_count"] == 0
    assert inventory["on_hand"] == []
    assert inventory["movements"] == []
    assert inventory["exceptions"] == []
    assert inventory["count_sessions"] == []
    assert inventory["reorder_signals"] == []
    assert inventory["valuations"] == []
    assert inventory["valuation_reversals"] == []
    assert inventory["cost_layers"] == []


def test_build_studio_demo_data_rejects_unmarked_input(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    manifest = json.loads((source / "demo_manifest.json").read_text(encoding="utf-8"))
    manifest["synthetic_data_only"] = False
    _write_json(source / "demo_manifest.json", manifest)

    with pytest.raises(StudioDemoBridgeError, match="accepts synthetic"):
        build_studio_demo_data(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_data_rejects_non_local_manifest(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    manifest = json.loads((source / "demo_manifest.json").read_text(encoding="utf-8"))
    manifest["external_calls"] = True
    _write_json(source / "demo_manifest.json", manifest)

    with pytest.raises(StudioDemoBridgeError, match="without external calls"):
        build_studio_demo_data(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_data_rejects_non_finite_metric(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    metrics_path = source / "reports" / "dashboard_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["records"][0]["value"] = float("nan")
    metrics_path.write_text(json.dumps(metrics).replace("NaN", "1e999"), encoding="utf-8")

    with pytest.raises(StudioDemoBridgeError, match="finite"):
        build_studio_demo_data(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_data_rejects_composite_or_control_text(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    exceptions_path = source / "reports" / "unified_exceptions.json"
    exceptions = json.loads(exceptions_path.read_text(encoding="utf-8"))
    exceptions["records"][0]["description"] = {"unexpected": "object"}
    _write_json(exceptions_path, exceptions)

    with pytest.raises(StudioDemoBridgeError, match="scalar value"):
        build_studio_demo_data(source, tmp_path / "studio-overview.json")

    _write_demo_package(source)
    exceptions = json.loads(exceptions_path.read_text(encoding="utf-8"))
    exceptions["records"][0]["description"] = "Synthetic description\u0000with a control character"
    _write_json(exceptions_path, exceptions)

    with pytest.raises(StudioDemoBridgeError, match="control characters"):
        build_studio_demo_data(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_data_rejects_oversized_json(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    entities_path = source / "sample_entities.json"
    with entities_path.open("ab") as handle:
        handle.truncate(MAX_SOURCE_FILE_BYTES + 1)

    with pytest.raises(StudioDemoBridgeError, match="exceeds"):
        build_studio_demo_data(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_bundle_rejects_invalid_evidence_checksum(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    evidence_path = source / "reports" / "evidence_registry.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["records"][0]["checksum_sha256"] = "not-a-checksum"
    _write_json(evidence_path, evidence)

    with pytest.raises(StudioDemoBridgeError, match="SHA-256"):
        build_studio_demo_bundle(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_bundle_rejects_invalid_inventory_quantity(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    inventory_path = source / "sample_inventory_control.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["records"][0]["quantity"] = "12.5000001"
    _write_json(inventory_path, inventory)

    with pytest.raises(StudioDemoBridgeError, match="exact decimal"):
        build_studio_demo_bundle(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_bundle_rejects_inconsistent_valuation_reversal(
    tmp_path: Path,
) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    inventory_path = source / "sample_inventory_control.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    reversal = next(
        record
        for record in inventory["records"]
        if record["record_type"] == "valuation_reversal"
    )
    reversal["reversal_movement_type"] = "Delivery"
    _write_json(inventory_path, inventory)

    with pytest.raises(StudioDemoBridgeError, match="movement types are inconsistent"):
        build_studio_demo_bundle(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_bundle_rejects_approved_reversal_without_finance_reference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    inventory_path = source / "sample_inventory_control.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    reversal = next(
        record
        for record in inventory["records"]
        if record["record_type"] == "valuation_reversal"
    )
    reversal["finance_entry_number"] = ""
    _write_json(inventory_path, inventory)

    with pytest.raises(StudioDemoBridgeError, match="Finance Draft reference"):
        build_studio_demo_bundle(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_bundle_rejects_inconsistent_cost_layer(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    inventory_path = source / "sample_inventory_control.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    layer = next(record for record in inventory["records"] if record["record_type"] == "cost_layer")
    layer["remaining_quantity"] = "0"
    layer["remaining_value"] = "10.00"
    _write_json(inventory_path, inventory)

    with pytest.raises(StudioDemoBridgeError, match="balances are inconsistent"):
        build_studio_demo_bundle(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_bundle_rejects_approved_valuation_without_finance_reference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    inventory_path = source / "sample_inventory_control.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    valuation = next(record for record in inventory["records"] if record["record_type"] == "valuation")
    valuation["finance_entry_number"] = ""
    _write_json(inventory_path, inventory)

    with pytest.raises(StudioDemoBridgeError, match="Finance Draft reference"):
        build_studio_demo_bundle(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_bundle_rejects_inconsistent_fifo_layer(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)
    inventory_path = source / "sample_inventory_control.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    layer = next(record for record in inventory["records"] if record["record_type"] == "cost_layer")
    layer["remaining_quantity"] = "13.000"
    _write_json(inventory_path, inventory)

    with pytest.raises(StudioDemoBridgeError, match="balances are inconsistent"):
        build_studio_demo_bundle(source, tmp_path / "studio-overview.json")


def test_build_studio_demo_data_rejects_unsafe_paths(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    _write_demo_package(source)

    with pytest.raises(StudioDemoBridgeError, match="Parent traversal"):
        build_studio_demo_data(source / ".." / "enterprise_demo", tmp_path / "studio-overview.json")
    with pytest.raises(StudioDemoBridgeError, match=".json"):
        build_studio_demo_data(source, tmp_path / "studio-overview.html")


def test_studio_data_cli_writes_contract_without_traceback(tmp_path: Path) -> None:
    source = tmp_path / "enterprise_demo"
    output = tmp_path / "studio-overview.json"
    _write_demo_package(source)

    result = runner.invoke(app, ["demo", "studio-data", "--input", str(source), "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert (tmp_path / STUDIO_EXCEPTION_QUEUE_FILENAME).exists()
    assert (tmp_path / STUDIO_EVIDENCE_BINDER_FILENAME).exists()
    assert (tmp_path / STUDIO_INVENTORY_CONTROL_FILENAME).exists()
    assert "allowlisted fields" in result.output
    assert "Traceback" not in result.output


def test_studio_data_cli_reports_safe_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["demo", "studio-data", "--input", str(tmp_path / "missing"), "--output", str(tmp_path / "output.json")],
    )

    assert result.exit_code == 1
    assert "existing local demo directory" in result.output
    assert "Traceback" not in result.output
