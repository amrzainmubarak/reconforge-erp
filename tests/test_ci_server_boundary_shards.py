"""The live CI partition must retain command coverage and fail-closed aggregation."""

from __future__ import annotations

import re
import shlex
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHARDS = {
    "writeback", "native", "parity", "durable-scale", "matching-runtime",
    "industry-close", "receivables", "finance-posting", "inventory-payables", "erp-expansion", "finance-reporting",
    "commercial-integrity", "supply-integrity", "finance-integrity",
    "supplier-returns", "fx-revaluation",
}
INTEGRITY_FILES = {
    "commercial-integrity": (
        "tests/test_postgres_commercial_collections.py", "tests/test_postgres_commercial_collection_cancellation.py",
        "tests/test_postgres_customer_returns.py",
    ),
    "supply-integrity": (
        "tests/test_postgres_landed_cost.py", "tests/test_postgres_landed_cost_api.py",
        "tests/test_postgres_landed_cost_cancellation.py",
        "tests/test_postgres_procurement_commitments.py", "tests/test_postgres_procurement_commitments_api.py",
    ),
    "finance-integrity": (
        "tests/test_postgres_fixed_assets.py", "tests/test_postgres_fixed_assets_evidence.py",
        "tests/test_postgres_global_operating_cycles.py", "tests/test_postgres_native_event_dispatch_migration.py",
        "tests/test_postgres_posting_snapshot_profile.py",
        "tests/test_postgres_operational_fx_tax.py", "tests/test_postgres_operational_fx_tax_api.py",
        "tests/test_postgres_operational_fx_tax_migration.py", "tests/test_postgres_financial_read_plans.py",
    ),
    "supplier-returns": ("tests/test_postgres_supplier_returns.py", "tests/test_postgres_supplier_returns_api.py"),
    "fx-revaluation": ("tests/test_postgres_operational_fx_revaluation.py", "tests/test_postgres_operational_fx_revaluation_migration.py"),
}
PROOF_OWNERS = {
    "verify_postgres_writeback_identity_migration_matrix.py": "writeback",
    "verify_writeback_receiver_idempotency.py": "writeback",
    "verify_postgres_writeback_receiver_idempotency_matrix.py": "writeback",
    "verify_postgres_writeback_receiver_failover_matrix.py": "writeback",
    "verify_postgres_writeback_recovery_compensation_matrix.py": "writeback",
    "verify_postgres_amlsim_reconciliation.py": "native",
}


def _workflow() -> dict[str, Any]:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def _partition(run: str) -> dict[str, list[str]]:
    """Reject unsupported shell structure instead of assuming its dispatch works."""
    case = run.split('case "$RECONFORGE_SERVER_BOUNDARY_SHARD" in\n', 1)[1]
    assert [line.strip() for line in case.splitlines()][-2:] == [
        '*) echo "Unknown server-boundary shard" >&2; exit 2 ;;', "esac",
    ]
    result: dict[str, list[str]] = {}
    owner: str | None = None
    for raw in case.splitlines():
        line = raw.strip()
        branch = re.fullmatch(r"([a-z-]+)\)(?: ;; # Dedicated evidence runners above own this shard\.)?", line)
        if branch:
            owner = branch.group(1)
            assert owner not in result
            result[owner] = []
        elif line.startswith("uv run --no-sync "):
            assert owner is not None
            result[owner].append(line)
        elif line == ";;":
            owner = None
        elif line.startswith("*)"):
            assert line == '*) echo "Unknown server-boundary shard" >&2; exit 2 ;;'
            owner = None
        elif line == "esac":
            break
        else:
            assert owner == "native", f"Unreviewed shell instruction outside native smoke: {line}"
    return result


def test_live_shards_remain_bounded_independent_and_observable() -> None:
    job = _workflow()["jobs"]["server-boundaries"]
    assert job["name"] == "server-boundaries (${{ matrix.shard }})"
    assert "needs" not in job  # Self-contained services must run after a pure-Python failure.
    assert _workflow()["jobs"]["test"]["strategy"]["fail-fast"] is False
    assert job["timeout-minutes"] == 30
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["max-parallel"] == 4
    shards = job["strategy"]["matrix"]["shard"]
    assert len(shards) == len(SHARDS) and set(shards) == SHARDS
    assert "continue-on-error" not in job
    assert all("continue-on-error" not in step for step in job["steps"])
    setup = {step["name"]: step for step in job["steps"]}
    for name in (
        "Install PostgreSQL native client tools", "Install locked server dependencies",
        "Create non-privileged PostgreSQL application role", "Run Alembic PostgreSQL migration",
    ):
        assert "if" not in setup[name], f"Every shard requires {name}."
    assert setup["Install locked server dependencies"]["run"] == (
        "uv sync --locked --all-extras --no-editable --python 3.12"
    )


def test_every_live_command_has_one_shard_and_proof_owner() -> None:
    job = _workflow()["jobs"]["server-boundaries"]
    live = next(step for step in job["steps"] if step["name"] == "Run live server-boundary tests")
    assert live["env"]["RECONFORGE_SERVER_BOUNDARY_SHARD"] == "${{ matrix.shard }}"
    assert live["env"]["PYTHONPATH"] == "${{ github.workspace }}"
    assert live["env"]["PYTEST_ADDOPTS"] == "-p tests.mandatory_native_gate"
    assert "if" not in live
    run = live["run"]
    assert run.startswith("set -euo pipefail\n")
    assert "|| true" not in run and "set +e" not in run
    groups = _partition(run)
    assert set(groups) == SHARDS
    assert groups["writeback"] == []  # Its five standalone proof runners precede this step.
    assert all(groups[shard] for shard in SHARDS - {"writeback"})
    commands = [command for group in groups.values() for command in group]
    assert len(commands) == 51  # Retain 46 original commands and all five complete Wave4 owner commands.
    assert all(count == 1 for count in Counter(commands).values())
    declared = [line.strip() for line in run.splitlines() if line.strip().startswith("uv run --no-sync ")]
    assert Counter(commands) == Counter(declared)
    for script, owner in PROOF_OWNERS.items():
        matches = [step for step in job["steps"] if script in step.get("run", "")]
        assert len(matches) == 1
        assert matches[0]["if"] == f"matrix.shard == '{owner}'"
    # The collection contract executes the producer and proves every inventory
    # module remains in parity or exactly one required expansion shard.
    assert "mapfile -t parity_tests" in run
    assert len(groups["parity"]) == 1
    assert 'pytest "${parity_tests[@]}"' in groups["parity"][0]
    assert "-k" not in shlex.split(groups["parity"][0])
    ar_api = "uv run --no-sync pytest tests/test_receivables_money_api_contract.py tests/test_receivables_policy_api.py -q"
    assert ar_api in groups["receivables"]
    recovery = "uv run --no-sync pytest tests/test_receivables_invoice_replay_domain.py tests/test_receivables_invoice_replay.py tests/test_receivables_invoice_recovery.py tests/test_receivables_invoice_replay_api.py tests/test_postgres_invoice_recovery_restore.py -q"
    assert recovery in groups["receivables"]
    receipt = "uv run --no-sync pytest tests/test_postgres_inventory_receipt_posting.py tests/test_postgres_inventory_receipt_api.py tests/test_postgres_inventory_receipt_migration.py tests/test_postgres_sales_revenue.py tests/test_postgres_sales_owner_closure.py tests/test_postgres_procurement_operations.py -q"
    assert receipt in groups["inventory-payables"]
    for filename, owner in (
        ("tests/test_postgres_sales_owner_closure.py", "inventory-payables"),
        ("tests/test_postgres_operational_finance_api.py", "finance-posting"),
        ("tests/test_postgres_financial_installments.py", "finance-reporting"),
        ("tests/test_postgres_financial_reporting.py", "finance-reporting"),
        ("tests/test_postgres_financial_reporting_api.py", "finance-reporting"),
        ("tests/test_postgres_stock_sales.py", "erp-expansion"),
        ("tests/test_postgres_stock_sales_api.py", "erp-expansion"),
        ("tests/test_postgres_procurement_partial.py", "erp-expansion"),
        ("tests/test_postgres_procurement_partial_api.py", "erp-expansion"),
        ("tests/test_postgres_stock_commerce.py", "erp-expansion"),
        ("tests/test_postgres_stock_commerce_api.py", "erp-expansion"),
        ("tests/test_postgres_stock_commerce_migrations.py", "erp-expansion"),
        ("tests/test_postgres_procurement_multiline.py", "erp-expansion"),
        ("tests/test_postgres_finance_posting_batches.py", "finance-posting"),
        ("tests/test_postgres_procurement_multiline_api.py", "erp-expansion"),
        ("tests/test_postgres_procurement_multiline_migrations.py", "erp-expansion"),
        ("tests/test_postgres_financial_reporting_snapshots.py", "finance-reporting"),
        ("tests/test_postgres_financial_snapshot_recovery.py", "finance-reporting"),
        ("tests/test_postgres_financial_snapshot_migration.py", "finance-reporting"),
        *((path, owner) for owner, paths in INTEGRITY_FILES.items() for path in paths),
    ):
        selected = [shard for shard, entries in groups.items()
                    for command in entries if filename in shlex.split(command)]
        assert selected == [owner], f"The owner regression requires one mandatory shard: {filename}"
    assert "verify_redis_live.py" in "\n".join(groups["native"])


def test_unconfigured_python_partition_cannot_drop_stock_native_coverage() -> None:
    workflow = _workflow()
    unit = next(step for step in workflow["jobs"]["test"]["steps"] if step["name"] == "Pytest")
    assert "if" not in unit and "continue-on-error" not in unit
    ignored = {
        "tests/test_postgres_stock_sales.py", "tests/test_postgres_stock_sales_api.py",
        "tests/test_postgres_stock_commerce.py", "tests/test_postgres_stock_commerce_api.py",
        "tests/test_postgres_stock_commerce_migrations.py",
        "tests/test_postgres_financial_reporting_snapshots.py", "tests/test_postgres_financial_snapshot_recovery.py",
        "tests/test_postgres_financial_snapshot_migration.py",
        *(path for paths in INTEGRITY_FILES.values() for path in paths),
    }
    tokens = shlex.split(unit["run"])
    assert tokens[:4] == ["uv", "run", "--no-sync", "pytest"]
    assert Counter(tokens[4:]) == Counter(f"--ignore={path}" for path in ignored)
    native = next(step for step in workflow["jobs"]["server-boundaries"]["steps"]
                  if step["name"] == "Run live server-boundary tests")
    groups = _partition(native["run"])
    owners = {path: owner for owner, paths in INTEGRITY_FILES.items() for path in paths}
    for path in ignored:
        assert [owner for owner, commands in groups.items()
                for command in commands if path in shlex.split(command)] == [
                    owners.get(path, "finance-reporting" if "financial_" in path else "erp-expansion")]


def test_integrity_owners_execute_complete_files_once_without_filtered_admission() -> None:
    job = _workflow()["jobs"]["server-boundaries"]
    live = next(step for step in job["steps"] if step["name"] == "Run live server-boundary tests")
    groups = _partition(live["run"])
    for owner, paths in INTEGRITY_FILES.items():
        selected = []
        for command in groups[owner]:
            tokens = shlex.split(command)
            assert tokens[:4] == ["uv", "run", "--no-sync", "pytest"]
            assert tokens[-1] == "-q"
            assert all(path.startswith("tests/") and path.endswith(".py") for path in tokens[4:-1])
            selected.extend(tokens[4:-1])
        assert Counter(selected) == Counter(paths), f"Every full owner file must execute once: {owner}"
    assert live["env"]["PYTEST_ADDOPTS"] == "-p tests.mandatory_native_gate"
    assert live["env"]["RECONFORGE_TEST_POSTGRES_APP_USER"] == "reconforge_app"
    assert "postgres" in job["services"]
    # Legacy commerce/procurement and their migration coverage remain separate.
    assert len(groups["erp-expansion"]) == 2


def test_enterprise_browser_matrix_requires_every_real_https_and_populated_restore_owner() -> None:
    job = _workflow()["jobs"]["enterprise-browser-recovery"]
    assert job["strategy"]["matrix"]["scenario"] == [
        "commerce", "procurement", "snapshots", "collections", "landed-cost", "fixed-assets",
        "procurement-commitments", "customer-returns", "supplier-returns", "operational-fx-tax",
    ]
    assert job["strategy"]["fail-fast"] is False
    assert "continue-on-error" not in job
    gate = next(step for step in job["steps"] if step["name"] == "Execute enterprise HTTPS cycle and populated native recovery")
    assert "if" not in gate and "continue-on-error" not in gate
    assert shlex.split(gate["run"]) == [
        "uv", "run", "--no-sync", "python", ".github/scripts/verify_erp_expansion_browser.py",
        "--scenario", "${{ matrix.scenario }}", "--verify-native-restore", "--output", "${{ runner.temp }}/enterprise-browser",
    ]
    upload = next(step for step in job["steps"] if step["name"] == "Retain source-bound enterprise recovery evidence")
    assert upload["if"] == "always()" and upload["with"]["if-no-files-found"] == "error"


def test_both_python_versions_inspect_built_publication_archives_and_retain_failures() -> None:
    job = _workflow()["jobs"]["test"]
    assert job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]
    steps = job["steps"]
    build = next(index for index, step in enumerate(steps) if step["name"] == "Build package")
    inspection = steps[build + 1]
    assert inspection["name"] == "Verify final source archive and wheel closure"
    assert "if" not in inspection and "continue-on-error" not in inspection
    assert shlex.split(inspection["run"]) == [
        "uv", "run", "--no-sync", "python", ".github/scripts/verify_global_integrity_archive.py",
        "--root", ".", "--sdist", "dist/reconforge_erp-0.7.1.tar.gz",
        "--wheel", "dist/reconforge_erp-0.7.1-py3-none-any.whl",
        "--report", "${RUNNER_TEMP}/publication-source-closure-${{ matrix.python-version }}.json",
    ]
    install = next(step for step in steps if step["name"] == "Install locked dependencies")
    assert "--all-extras" in shlex.split(install["run"])
    assert "--locked" in shlex.split(install["run"])
    upload = steps[build + 2]
    assert upload["name"] == "Retain final source archive inspection" and upload["if"] == "always()"
    assert "continue-on-error" not in upload
    assert re.fullmatch(r"actions/upload-artifact@[a-f0-9]{40}", upload["uses"])
    assert upload["with"] == {
        "name": "publication-source-closure-${{ matrix.python-version }}",
        "path": "${{ runner.temp }}/publication-source-closure-${{ matrix.python-version }}.json",
        "if-no-files-found": "error",
    }


def test_native_services_and_unconditional_report_retention_survive_partition() -> None:
    job = _workflow()["jobs"]["server-boundaries"]
    live = next(step for step in job["steps"] if step["name"] == "Run live server-boundary tests")
    assert live["env"]["PGSERVICEFILE"] == "${{ runner.temp }}/reconforge-pgservice.conf"
    assert live["env"]["RECONFORGE_TEST_POSTGRES_SOURCE_SERVICE"] == "reconforge_ci_source"
    assert live["env"]["RECONFORGE_TEST_POSTGRES_MAINTENANCE_SERVICE"] == "reconforge_ci_admin"
    assert 'chmod 600 "$PGSERVICEFILE"' in live["run"]
    assert 'pg_dump --format=custom --no-owner --no-privileges --file "$native_smoke_dump" --dbname service=reconforge_ci_source' in live["run"]
    assert 'test -s "$native_smoke_dump"' in live["run"]
    assert 'pg_restore --list "$native_smoke_dump"' in live["run"]
    uploads = [step for step in job["steps"] if step["name"].startswith("Upload ")]
    assert len(uploads) == 8
    assert all(step["if"] == "always()" for step in uploads)
    names = [step["with"]["name"] for step in uploads]
    assert len(names) == len(set(names))
    assert len({step["uses"] for step in uploads}) == 1
    # Each report has exactly one producing shard; other shards have no such file.
    # Existing always-upload handling still retains partial reports on failure.
    assert all(step["with"]["if-no-files-found"] == "ignore" for step in uploads)
    assert live["env"]["RECONFORGE_AR_INVOICE_REPLAY_NATIVE_REPORT"] == "${{ runner.temp }}/reconforge-ar-invoice-recovery-native.json"


def test_exact_required_check_name_only_accepts_matrix_success() -> None:
    gate = _workflow()["jobs"]["server-boundaries-gate"]
    assert gate["name"] == "server-boundaries"
    assert gate["needs"] == ["server-boundaries"]
    assert gate["if"] == "always()"
    assert gate["timeout-minutes"] == 5
    assert "continue-on-error" not in gate
    assert len(gate["steps"]) == 1
    step = gate["steps"][0]
    assert "if" not in step and "continue-on-error" not in step
    assert step["env"] == {"SHARDS_RESULT": "${{ needs.server-boundaries.result }}"}
    assert step["run"].splitlines() == [
        "set -euo pipefail",
        'printf \'Server-boundary matrix result: %s\\n\' "$SHARDS_RESULT"',
        'test "$SHARDS_RESULT" = success',
    ]
