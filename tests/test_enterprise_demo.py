from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app

runner = CliRunner()


def test_enterprise_demo_command_creates_expected_local_package(tmp_path: Path) -> None:
    output = tmp_path / "enterprise_demo"

    result = runner.invoke(app, ["demo", "enterprise", "--output", str(output)])

    assert result.exit_code == 0, result.output
    expected_paths = [
        "README.md",
        "demo_walkthrough.md",
        "demo_script.md",
        "demo_manifest.json",
        "screenshots_checklist.md",
        "sample_entities.json",
        "sample_periods.json",
        "sample_trial_balance.csv",
        "sample_journals.csv",
        "sample_intercompany.csv",
        "sample_controls.csv",
        "sample_account_reconciliations.json",
        "sample_close_tasks.json",
        "sample_inventory_control.json",
        "sample_evidence_references.json",
        "sample_matching_left.csv",
        "sample_matching_right.csv",
        "sample_unified_exceptions.json",
        "sample_metrics.json",
        "sample_evidence/trial_balance_support.md",
        "reports/dashboard_metrics.json",
        "reports/dashboard_summary.md",
        "reports/unified_exceptions.json",
    ]
    for relative_path in expected_paths:
        assert (output / relative_path).exists(), relative_path
    assert not (output / "reconforge.db").exists()

    manifest = json.loads((output / "demo_manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic_data_only"] is True
    assert manifest["synthetic_data_marker"] == "SYNTHETIC_ENTERPRISE_DEMO_ONLY"
    assert manifest["local_first"] is True
    assert manifest["external_calls"] is False
    assert manifest["database"]["created"] is False
    assert manifest["record_counts"]["entities"] == 3
    assert manifest["record_counts"]["periods"] == 2
    assert manifest["record_counts"]["trial_balance_rows"] == 36
    assert manifest["record_counts"]["matching_matched"] == 3

    readme = (output / "README.md").read_text(encoding="utf-8")
    walkthrough = (output / "demo_walkthrough.md").read_text(encoding="utf-8")
    trial_balance = (output / "sample_trial_balance.csv").read_text(encoding="utf-8")
    assert "SYNTHETIC_ENTERPRISE_DEMO_ONLY" in readme
    assert "SYNTHETIC_ENTERPRISE_DEMO_ONLY" in walkthrough
    assert "SYNTHETIC_ENTERPRISE_DEMO_ONLY" in trial_balance


def test_enterprise_demo_manifest_is_deterministic_for_file_package(tmp_path: Path) -> None:
    output = tmp_path / "enterprise_demo"

    first = runner.invoke(app, ["demo", "enterprise", "--output", str(output)])
    first_manifest = json.loads((output / "demo_manifest.json").read_text(encoding="utf-8"))
    second = runner.invoke(app, ["demo", "enterprise", "--output", str(output)])
    second_manifest = json.loads((output / "demo_manifest.json").read_text(encoding="utf-8"))

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert first_manifest == second_manifest
    manifest_paths = [item["path"] for item in second_manifest["generated_files"]]
    assert manifest_paths == sorted(manifest_paths)


def test_enterprise_demo_optional_db_is_seeded_inside_output_folder(tmp_path: Path) -> None:
    output = tmp_path / "enterprise_demo"
    db_path = output / "reconforge.db"

    result = runner.invoke(app, ["demo", "enterprise", "--output", str(output), "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert db_path.exists()
    manifest = json.loads((output / "demo_manifest.json").read_text(encoding="utf-8"))
    assert manifest["database"] == {"created": True, "path": "reconforge.db", "requested": True}
    assert "reconforge.db" in {item["path"] for item in manifest["generated_files"]}

    connection = sqlite3.connect(db_path)
    try:
        account_count = connection.execute("SELECT COUNT(*) FROM account_reconciliation_records").fetchone()[0]
        exception_count = connection.execute("SELECT COUNT(*) FROM exceptions_queue").fetchone()[0]
        metric_count = connection.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0]
    finally:
        connection.close()
    assert account_count == 36
    assert exception_count >= 4
    assert metric_count == 8


def test_enterprise_demo_output_avoids_fake_promotional_claims(tmp_path: Path) -> None:
    output = tmp_path / "enterprise_demo"

    result = runner.invoke(app, ["demo", "enterprise", "--output", str(output)])

    assert result.exit_code == 0, result.output
    combined = "\n".join(
        [
            (output / "README.md").read_text(encoding="utf-8"),
            (output / "demo_walkthrough.md").read_text(encoding="utf-8"),
            (output / "demo_script.md").read_text(encoding="utf-8"),
            (output / "screenshots_checklist.md").read_text(encoding="utf-8"),
            (output / "reports" / "dashboard_summary.md").read_text(encoding="utf-8"),
        ],
    ).lower()
    for forbidden in [
        "trusted by",
        "logo wall",
        "testimonial from",
        "customer success story",
        "roi of",
        "enterprise-ready",
        "sox compliant",
        "soc 2 certified",
        "iso certified",
        "audit opinion issued",
        "vendor replacement",
    ]:
        assert forbidden not in combined
    assert "no real customers" in combined
    assert "no fake roi" in combined
    assert "local-first demo" in combined


def test_showcase_command_builds_one_cohesive_local_demo(tmp_path: Path) -> None:
    output = tmp_path / "showcase" / "enterprise_demo"
    studio_output = tmp_path / "web" / "demo" / "studio-overview.json"

    result = runner.invoke(
        app,
        [
            "demo",
            "showcase",
            "--output",
            str(output),
            "--studio-output",
            str(studio_output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Showcase ready" in result.output
    assert "external calls" in result.output
    assert "Traceback" not in result.output
    assert (output / "demo_manifest.json").exists()
    assert (output / "demo_walkthrough.md").exists()
    expected_contracts = {
        "studio-overview.json",
        "studio-exceptions.json",
        "studio-evidence.json",
        "studio-inventory.json",
    }
    assert {path.name for path in studio_output.parent.glob("studio-*.json")} == expected_contracts
    overview = json.loads(studio_output.read_text(encoding="utf-8"))
    assert overview["executive_brief"]["readiness_status"] == "attention"
    assert [record["domain"] for record in overview["control_domains"]] == [
        "close",
        "evidence",
        "matching",
        "controls",
    ]
    assert len(overview["entity_health"]) == 3
    assert overview["source"]["external_calls"] is False


def test_enterprise_demo_rejects_traversal_output_without_traceback(tmp_path: Path) -> None:
    traversal_output = tmp_path / "parent" / ".." / "enterprise_demo"

    result = runner.invoke(app, ["demo", "enterprise", "--output", str(traversal_output)])

    assert result.exit_code == 1
    assert "Unsafe demo output path" in result.output
    assert "Traceback" not in result.output
