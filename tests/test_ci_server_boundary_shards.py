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
    "worker-amount-safety", "quality-direct-safety",
    "industry-close", "receivables", "finance-posting", "inventory-payables", "erp-expansion", "finance-reporting",
    "commercial-integrity", "customer-partial-cycle", "customer-partial-security", "customer-partial-rounding", "supply-integrity", "finance-integrity",
    "customer-partial-rounding-migration", "customer-partial-rounding-security",
    "customer-partial-monetary",
    "customer-partial-monetary-migration", "customer-partial-monetary-security",
    "supplier-returns", "fx-revaluation",
    "manufacturing-execution", "intercompany-operations", "intercompany-cashflow", "intercompany-group-reporting", "procurement-sourcing", "procurement-sourcing-api", "manufacturing-sourcing",
    "people-project-payroll", "accrual-deferral", "manufacturing-supply-plan", "project-time-billing", "project-source-reconciliation", "inventory-transfer",
}
INTEGRITY_FILES = {
    "inventory-transfer": ("tests/test_postgres_inventory_transfer.py", "tests/test_postgres_inventory_transfer_integration.py", "tests/test_postgres_inventory_transfer_read_authority.py", "tests/test_postgres_inventory_transfer_browser.py", "tests/test_postgres_inventory_transfer_concurrency.py"),
    "manufacturing-supply-plan": ("tests/test_postgres_manufacturing_supply_closure.py", "tests/test_postgres_manufacturing_supply_closure_authority.py", "tests/test_postgres_manufacturing_supply_plan.py", "tests/test_postgres_manufacturing_supply_browser_seed.py", "tests/test_postgres_manufacturing_supply_read_authority.py"),
    "project-time-billing": (
        "tests/test_postgres_project_time_billing.py", "tests/test_postgres_project_time_billing_api.py",
        "tests/test_postgres_project_time_billing_restore.py", "tests/test_postgres_project_time_billing_read_authority.py",
    ),
    "project-source-reconciliation": (
        "tests/test_postgres_project_source_close.py",
        "tests/test_postgres_project_source_reconciliation.py", "tests/test_postgres_project_source_reconciliation_api.py",
        "tests/test_postgres_project_source_reconciliation_browser_fixture.py",
    ),
    "accrual-deferral": (
        "tests/test_postgres_accrual_deferral.py", "tests/test_postgres_accrual_deferral_api.py",
        "tests/test_postgres_accrual_deferral_guards.py", "tests/test_postgres_accrual_deferral_ownership.py",
        "tests/test_postgres_accrual_deferral_restore.py",
    ),
    "commercial-integrity": (
        "tests/test_postgres_commercial_collections.py", "tests/test_postgres_commercial_collection_cancellation.py",
        "tests/test_postgres_customer_returns.py", "tests/test_postgres_customer_return_read_authority.py",
    ),
    "customer-partial-cycle": (
        "tests/test_postgres_customer_partial_return_source.py", "tests/test_postgres_customer_partial_returns.py",
        "tests/test_postgres_customer_partial_return_transfer.py",
    ),
    "customer-partial-security": ("tests/test_postgres_customer_partial_return_posted_security.py",),
    "customer-partial-rounding": (
        "tests/test_postgres_customer_partial_return_rounding.py",
        "tests/test_postgres_customer_partial_return_zero_stock.py",
    ),
    "customer-partial-rounding-migration": ("tests/test_postgres_customer_partial_return_rounding_migration.py",),
    "customer-partial-monetary": ("tests/test_postgres_monetary_customer_partial_returns.py",),
    "customer-partial-monetary-migration": ("tests/test_postgres_monetary_customer_return_migration.py",),
    "customer-partial-monetary-security": ("tests/test_postgres_monetary_customer_return_security.py",),
    "customer-partial-rounding-security": (
        "tests/test_postgres_customer_partial_return_rounding_security.py",
        "tests/test_postgres_customer_partial_return_zero_stock_security.py",
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
        "tests/test_postgres_stock_sales_reversal_dispatch.py",
        "tests/test_postgres_operational_fx_tax.py", "tests/test_postgres_operational_fx_tax_api.py",
        "tests/test_postgres_operational_fx_tax_migration.py", "tests/test_postgres_financial_read_plans.py",
    ),
    "supplier-returns": ("tests/test_postgres_supplier_returns.py", "tests/test_postgres_supplier_returns_api.py"),
    "fx-revaluation": ("tests/test_postgres_operational_fx_revaluation.py", "tests/test_postgres_operational_fx_revaluation_migration.py"),
    "manufacturing-execution": (
        "tests/test_postgres_manufacturing_execution.py", "tests/test_postgres_wave5_migrations.py",
        "tests/test_postgres_inventory_scope.py", "tests/test_postgres_inventory_quantity_contracts.py",
        "tests/test_postgres_manufacturing_execution_v2.py", "tests/test_postgres_enterprise_migrations.py",
    ),
    "quality-direct-safety": ("tests/test_quality_direct_update_authority_20261028.py",),
    "worker-amount-safety": ("tests/test_worker_policy_amount_postgres_20261028.py",),
    "intercompany-operations": ("tests/test_postgres_intercompany_operations.py", "tests/test_postgres_intercompany_operations_api.py",
                               "tests/test_postgres_intercompany_fx.py", "tests/test_postgres_intercompany_fx_api.py"),
    "intercompany-cashflow": ("tests/test_postgres_intercompany_cashflow.py", "tests/test_postgres_intercompany_cashflow_api.py",
                             "tests/test_postgres_intercompany_cashflow_authority.py", "tests/test_postgres_intercompany_cashflow_restore.py",
                             "tests/test_intercompany_cashflow_browser_fixture.py"),
    "intercompany-group-reporting": ("tests/test_postgres_intercompany_fx_native_evidence_bundle.py",
        "tests/test_postgres_intercompany_reporting_currency_precision.py", "tests/test_postgres_intercompany_fx_reporting_authority.py",
        "tests/test_postgres_intercompany_group_diagnostic.py", "tests/test_postgres_intercompany_group_diagnostic_api.py",
        "tests/test_intercompany_group_diagnostic_browser_fixture.py"),
    "people-project-payroll": ("tests/test_postgres_people_project_payroll.py", "tests/test_postgres_people_project_payroll_api.py", "tests/test_postgres_people_project_payroll_restore.py", "tests/test_postgres_people_project_dimension_pins.py", "tests/test_postgres_people_project_read_authority.py"),
    "procurement-sourcing": ("tests/test_postgres_procurement_sourcing.py",),
    "procurement-sourcing-api": ("tests/test_postgres_procurement_sourcing_api.py",),
    "manufacturing-sourcing": ("tests/test_postgres_manufacturing_sourcing.py",),
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


def test_recent_safety_regressions_run_in_mandatory_native_shards() -> None:
    workflow = _workflow()
    live = next(step for step in workflow["jobs"]["server-boundaries"]["steps"]
                if step["name"] == "Run live server-boundary tests")
    assert live["env"]["PYTEST_ADDOPTS"] == "-p tests.mandatory_native_gate"
    grant = next(step for step in workflow["jobs"]["server-boundaries"]["steps"]
                 if step["name"] == "Grant synthetic safety fixture table access")
    assert grant["if"] == "matrix.shard == 'worker-amount-safety' || matrix.shard == 'quality-direct-safety'"
    assert "ALL TABLES" not in grant["run"] and "DELETE" not in grant["run"]
    assert "--set ON_ERROR_STOP=1" in grant["run"]
    steps = workflow["jobs"]["server-boundaries"]["steps"]
    migration = next(step for step in steps if step["name"] == "Run Alembic PostgreSQL migration")
    assert steps.index(migration) < steps.index(grant) < steps.index(live)
    groups = _partition(live["run"])
    required = {
        "tests/test_quality_direct_update_authority_20261028.py": "quality-direct-safety",
        "tests/test_worker_policy_amount_postgres_20261028.py": "worker-amount-safety",
    }
    for path, owner in required.items():
        selected = [shard for shard, commands in groups.items()
                    for command in commands if path in shlex.split(command)]
        assert selected == [owner], f"{path} must run in its mandatory native shard"
        command = next(command for command in groups[owner] if path in shlex.split(command))
        assert "-k" not in shlex.split(command)
    generic = next(step for step in workflow["jobs"]["test"]["steps"] if step["name"] == "Pytest")
    assert all(f"--ignore={path}" in shlex.split(generic["run"]) for path in required)
    organization_test = "tests/test_reconciliation_worker_organization_native.py"
    zero_retry_test = "tests/test_reconciliation_zero_retry.py"
    exception_collision_test = "tests/test_reconciliation_exception_collision.py"
    canonical_source_test = "tests/test_reconciliation_canonical_source_native.py"
    result_collision_test = "tests/test_reconciliation_result_collision.py"
    result_values_test = "tests/test_reconciliation_result_values.py"
    assert f"--ignore={organization_test}" in shlex.split(generic["run"])
    assert f"--ignore={zero_retry_test}" in shlex.split(generic["run"])
    assert f"--ignore={exception_collision_test}" in shlex.split(generic["run"])
    assert f"--ignore={canonical_source_test}" in shlex.split(generic["run"])
    assert f"--ignore={result_collision_test}" in shlex.split(generic["run"])
    assert f"--ignore={result_values_test}" in shlex.split(generic["run"])
    organization = next(step for step in steps
                        if step["name"] == "Verify reconciliation worker safety on dedicated databases")
    assert organization["if"] == "matrix.shard == 'worker-amount-safety'"
    assert "continue-on-error" not in organization
    assert organization["env"]["PYTEST_ADDOPTS"] == "-p tests.mandatory_native_gate"
    assert organization["env"]["RECONFORGE_OWNED_TEST_POSTGRES_ADMIN_DSN"] == "postgresql://postgres:postgres@localhost:5432/postgres"
    assert organization["env"]["RECONFORGE_OWNED_TEST_POSTGRES_DSN"] == "postgresql://reconforge_app:reconforge_app@localhost:5432/postgres"
    assert shlex.split(organization["run"]) == [
        "uv", "run", "--no-sync", "pytest", organization_test, zero_retry_test,
        exception_collision_test, canonical_source_test, result_collision_test, result_values_test, "-q"
    ]
    assert steps.index(live) < steps.index(organization)
    assert all(not any(key.startswith("RECONFORGE_OWNED_TEST_POSTGRES_") for key in step.get("env", {}))
               for step in steps if step is not organization)


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
    assert len(commands) == 82  # Both new safety owners execute unfiltered native files.
    assert all(count == 1 for count in Counter(commands).values())
    assert "uv run --no-sync pytest tests/test_postgres_grouped_matching_guard_20261027.py -q" in groups["matching-runtime"]
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
        ("tests/test_postgres_grouped_matching_guard_20261027.py", "matching-runtime"),
        ("tests/test_worker_policy_amount_postgres_20261028.py", "worker-amount-safety"),
        ("tests/test_quality_direct_update_authority_20261028.py", "quality-direct-safety"),
        ("tests/test_postgres_operational_finance_api.py", "finance-posting"),
        ("tests/test_postgres_financial_installments.py", "finance-reporting"),
        ("tests/test_postgres_financial_reporting.py", "finance-reporting"),
        ("tests/test_postgres_financial_reporting_api.py", "finance-reporting"),
        ("tests/test_postgres_stock_sales.py", "erp-expansion"),
        ("tests/test_postgres_stock_sales_read_authority.py", "erp-expansion"),
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
        ("tests/test_receivables_credit_integrity.py", "receivables"),
        ("tests/test_receivables_aging_integrity.py", "receivables"),
        *((path, owner) for owner, paths in INTEGRITY_FILES.items() for path in paths),
    ):
        selected = [shard for shard, entries in groups.items()
                    for command in entries if filename in shlex.split(command)]
        assert selected == [owner], f"The owner regression requires one mandatory shard: {filename}"
    for selector in (
        "tests/test_api_federation.py::test_live_http_oidc_session_logout_replay_and_tenant_isolation",
        "tests/test_api_scim.py::test_live_scim_http_auth_lifecycle_etag_filter_and_tenant_isolation",
        "tests/test_api_service_accounts.py::test_live_service_credential_http_auth_policy_tenant_and_logout",
        "tests/test_postgres_master_data_application.py::test_live_postgres_master_data_application_workspace_and_tenant_isolation",
        "tests/test_postgres_notifications.py::test_live_postgres_scheduler_notifications_are_atomic_scoped_retryable_and_audited",
        "tests/test_postgres_scheduler.py::test_live_postgres_scheduler_is_atomic_idempotent_coordinated_and_scoped",
        "tests/test_postgres_scim.py::test_live_postgres_scim_idempotency_deactivation_sessions_and_rls",
        "tests/test_postgres_scim_auth.py::test_live_scim_credential_rotation_revocation_expiry_and_rls",
    ):
        assert [shard for shard, entries in groups.items()
                for command in entries if selector in shlex.split(command)] == ["native"]
    assert "verify_redis_live.py" in "\n".join(groups["native"])


def test_unconfigured_python_partition_cannot_drop_stock_native_coverage() -> None:
    workflow = _workflow()
    unit = next(step for step in workflow["jobs"]["test"]["steps"] if step["name"] == "Pytest")
    assert "if" not in unit and "continue-on-error" not in unit
    release_files = {
        "tests/test_postgres_enterprise_finance_bridge.py",
        "tests/test_release_product_scope.py",
        "tests/test_crm_authority_postgres_20261026.py",
        "tests/test_enterprise_program_stock_to_cash.py",
        "tests/test_enterprise_program_asset_authority.py",
        "tests/test_enterprise_program_hcm_migration.py",
        "tests/test_enterprise_program_capacity_quality.py",
        "tests/test_enterprise_program_quality_authority.py",
        "tests/test_release_authorization_postgres.py",
    }
    ignored = {
        "tests/test_reconciliation_worker_organization_native.py",
        "tests/test_reconciliation_zero_retry.py",
        "tests/test_reconciliation_exception_collision.py",
        "tests/test_reconciliation_canonical_source_native.py",
        "tests/test_reconciliation_result_collision.py",
        "tests/test_reconciliation_result_values.py",
        "tests/test_postgres_grouped_matching_guard_20261027.py",
        "tests/test_worker_policy_amount_postgres_20261028.py",
        "tests/test_quality_direct_update_authority_20261028.py",
        "tests/test_postgres_financial_source_roles.py",
        "tests/test_postgres_stock_sales.py", "tests/test_postgres_stock_sales_api.py",
        "tests/test_postgres_stock_sales_read_authority.py",
        "tests/test_postgres_stock_commerce.py", "tests/test_postgres_stock_commerce_api.py",
        "tests/test_postgres_stock_commerce_migrations.py",
        "tests/test_postgres_financial_reporting_snapshots.py", "tests/test_postgres_financial_snapshot_recovery.py",
        "tests/test_postgres_financial_snapshot_migration.py",
        *(path for paths in INTEGRITY_FILES.values() for path in paths),
    }
    tokens = shlex.split(unit["run"])
    assert tokens[:4] == ["uv", "run", "--no-sync", "pytest"]
    assert Counter(tokens[4:]) == Counter(f"--ignore={path}" for path in ignored | release_files)
    release = next(step for step in workflow["jobs"]["release-product-browser"]["steps"]
                   if step["name"] == "Verify native CRM authority and canonical bridge recovery")
    assert "if" not in release and "continue-on-error" not in release
    assert release["env"]["PYTEST_ADDOPTS"] == "-p tests.mandatory_native_gate"
    assert shlex.split(release["run"])[:4] == ["uv", "run", "--no-sync", "pytest"]
    assert Counter(shlex.split(release["run"])[4:]) == Counter([*release_files, "-q"])
    native = next(step for step in workflow["jobs"]["server-boundaries"]["steps"]
                  if step["name"] == "Run live server-boundary tests")
    groups = _partition(native["run"])
    owners = {path: owner for owner, paths in INTEGRITY_FILES.items() for path in paths}
    owners["tests/test_postgres_grouped_matching_guard_20261027.py"] = "matching-runtime"
    owners["tests/test_worker_policy_amount_postgres_20261028.py"] = "worker-amount-safety"
    owners["tests/test_quality_direct_update_authority_20261028.py"] = "quality-direct-safety"
    # These regressions share a separate conditional step with its own
    # process-scoped DSNs and are checked above; all others use the case map.
    separately_owned = {
        "tests/test_reconciliation_worker_organization_native.py", "tests/test_reconciliation_zero_retry.py",
        "tests/test_reconciliation_exception_collision.py", "tests/test_reconciliation_canonical_source_native.py",
        "tests/test_reconciliation_result_collision.py", "tests/test_reconciliation_result_values.py",
    }
    for path in ignored - separately_owned:
        assert [owner for owner, commands in groups.items()
                for command in commands if path in shlex.split(command)] == [
                    owners.get(path, "finance-posting" if path == "tests/test_postgres_financial_source_roles.py"
                               else "finance-reporting" if "financial_" in path else "erp-expansion")]


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


def test_primary_studio_shell_is_a_required_real_browser_gate_with_public_evidence() -> None:
    job = _workflow()["jobs"]["release-product-browser"]
    build = next(step for step in job["steps"] if step["name"] == "Build the real application component harness")
    assert "build --outDir ../../output/assurance-20261026/studio-shell/web" in build["run"]
    gate = next(step for step in job["steps"] if step["name"] == "Verify authenticated primary Studio shell and responsive access")
    assert "if" not in gate and "continue-on-error" not in gate
    assert [shlex.split(command) for command in gate["run"].strip().splitlines()] == [
        ["node", "apps/web/node_modules/@playwright/test/cli.js", "test", "--config", "apps/web/e2e/studio-shell.playwright.config.ts"],
        ["node", "apps/web/e2e/studio-shell.manifest.mjs"],
    ]
    assert gate["env"]["RECONFORGE_RELEASE_PRODUCT_PYTHON"] == "${{ github.workspace }}/.venv/bin/python"
    upload = next(step for step in job["steps"] if step["name"] == "Retain primary Studio accessibility and visual evidence")
    assert upload["if"] == "always()" and upload["with"]["if-no-files-found"] == "error"
    assert set(upload["with"]["path"].splitlines()) == {
        "output/assurance-20261026/studio-shell/measurements.json",
        "output/assurance-20261026/studio-shell/screenshot-manifest.json",
        "output/assurance-20261026/studio-shell/axe-*.json",
        "output/assurance-20261026/studio-shell/authenticated-*.png",
    }


def test_release_product_browser_uses_postgres_16_native_tools_before_restore() -> None:
    job = _workflow()["jobs"]["release-product-browser"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["services"]["postgres"]["image"].startswith("postgres:16.")
    steps = job["steps"]
    install = next(step for step in steps if step["name"] == "Install PostgreSQL 16 native client tools")
    gate = next(step for step in steps if step["name"] == "Verify native CRM authority and canonical bridge recovery")
    assert steps.index(install) < steps.index(gate)
    assert "if" not in install and "continue-on-error" not in install
    assert "sudo apt-get install --no-install-recommends -y libpq-dev postgresql-client-16" in install["run"]
    assert 'export PATH="/usr/lib/postgresql/16/bin:$PATH"' in install["run"]
    assert "verify_postgres_native_tools.py --expected-major 16 --print-bindir" in install["run"]
    assert "pg_dump --version" in install["run"]
    assert "pg_restore --version" in install["run"]
    assert 'printf \'%s\\n\' "$native_bindir" >> "$GITHUB_PATH"' in install["run"]


def test_enterprise_browser_matrix_requires_every_real_https_and_populated_restore_owner() -> None:
    job = _workflow()["jobs"]["enterprise-browser-recovery"]
    assert job["strategy"]["matrix"]["scenario"] == [
        "commerce", "procurement", "snapshots", "collections", "landed-cost", "fixed-assets",
        "procurement-commitments", "customer-returns", "customer-partial-returns",
        "customer-partial-return-remainder-ordinary", "customer-partial-return-remainder-zero", "customer-partial-return-remainder-refund",
        "customer-partial-return-restituted",
        "customer-partial-return-monetary-identity", "customer-partial-return-monetary-foreign",
        "supplier-returns", "operational-fx-tax",
        "manufacturing-execution", "manufacturing-execution-v2", "intercompany-operations", "intercompany-fx", "intercompany-source-cashflow", "intercompany-group-diagnostic", "people-project-payroll", "procurement-sourcing",
        "accrual-deferral", "project-time-billing", "project-source-reconciliation", "manufacturing-supply-plan", "inventory-transfer",
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


def test_server_boundaries_pins_runner_and_postgres_16_client() -> None:
    job = _workflow()["jobs"]["server-boundaries"]
    # ubuntu-latest moved to 26.04, where the runner's apt sources did not
    # provide the client version required by the PostgreSQL 16 service.
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["services"]["postgres"]["image"].startswith("postgres:16.")
    install = next(step for step in job["steps"] if step["name"] == "Install PostgreSQL native client tools")
    assert "if" not in install and "continue-on-error" not in install
    assert "sudo apt-get install --no-install-recommends -y libpq-dev postgresql-client-16" in install["run"]
    assert "verify_postgres_native_tools.py --expected-major 16 --print-bindir" in install["run"]
    assert 'printf \'%s\\n\' "$native_bindir" >> "$GITHUB_PATH"' in install["run"]


def test_native_services_and_unconditional_report_retention_survive_partition() -> None:
    job = _workflow()["jobs"]["server-boundaries"]
    live = next(step for step in job["steps"] if step["name"] == "Run live server-boundary tests")
    assert live["env"]["PGSERVICEFILE"] == "${{ runner.temp }}/reconforge-pgservice.conf"
    assert live["env"]["RECONFORGE_TEST_POSTGRES_SOURCE_SERVICE"] == "reconforge_ci_source"
    assert live["env"]["RECONFORGE_TEST_POSTGRES_MAINTENANCE_SERVICE"] == "reconforge_ci_admin"
    assert 'chmod 600 "$PGSERVICEFILE"' in live["run"]
    assert live["env"]["RECONFORGE_CASHFLOW_PROOF_DIR"] == "${{ runner.temp }}/reconforge-cashflow-native-private"
    assert 'mkdir -p "$RECONFORGE_CASHFLOW_PROOF_DIR"' in live["run"]
    assert 'chmod 700 "$RECONFORGE_CASHFLOW_PROOF_DIR"' in live["run"]
    assert live["run"].index('mkdir -p "$RECONFORGE_CASHFLOW_PROOF_DIR"') < live["run"].index('case "$RECONFORGE_SERVER_BOUNDARY_SHARD" in')
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
