"""Execute CI collection to prevent benchmark filters hiding server contracts."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
JOBS_MODULE = "tests/test_postgres_durable_jobs.py"


def test_live_ci_general_gate_collects_every_advertised_contract() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]
    run = next(step["run"] for step in steps if step.get("name") == "Run live server-boundary tests")
    lines = run.splitlines()
    producer = next(line for line in lines if line.startswith("mapfile -t parity_tests "))
    quoted_code = re.search(r'python -c ("(?:\\.|[^"\\])*")\)', producer)
    assert quoted_code is not None, "The CI parity inventory producer must remain inspectable."
    inventory_result = subprocess.run(  # noqa: S603 - checked-in inventory producer, never shell execution
        [sys.executable, "-c", shlex.split(quoted_code.group(1))[0]],
        cwd=ROOT, capture_output=True, text=True, check=True, timeout=30,
    )
    parity_modules = inventory_result.stdout.splitlines()
    inventory = yaml.safe_load((ROOT / "docs/execution/POSTGRES_PARITY_INVENTORY.yaml").read_text(encoding="utf-8"))
    expected_parity = {
        path for row in inventory["boundaries"]
        if row.get("ci_shard", "parity") == "parity"
        for path in [row.get("test"), *row.get("additional_tests", [])] if path
    } - {JOBS_MODULE}
    assert set(parity_modules) == expected_parity
    assert "tests/test_postgres_payables_payment_link_reversal.py" in parity_modules
    delegated = {
        path: row["ci_shard"] for row in inventory["boundaries"] if "ci_shard" in row
        for path in [row.get("test"), *row.get("additional_tests", [])] if path
    }
    assert delegated == {
        "tests/test_postgres_stock_sales.py": "erp-expansion",
        "tests/test_postgres_stock_sales_api.py": "erp-expansion",
        "tests/test_postgres_procurement_partial.py": "erp-expansion",
        "tests/test_postgres_procurement_partial_api.py": "erp-expansion",
        "tests/test_postgres_financial_installments.py": "finance-reporting",
        "tests/test_postgres_financial_reporting.py": "finance-reporting",
        "tests/test_postgres_financial_reporting_api.py": "finance-reporting",
    }
    # Delegation must name a required native branch and retain complete modules.
    for path, owner in delegated.items():
        branch = run.split(f"{owner})\n", 1)[1].split(";;", 1)[0]
        commands = [shlex.split(line) for line in branch.splitlines() if "pytest " in line]
        assert sum(path in command for command in commands) == 1
        assert all("-k" not in command and "--deselect" not in command for command in commands)

    command = shlex.split(next(line for line in lines if 'pytest "${parity_tests[@]}"' in line))
    arguments = command[command.index("pytest") + 1:]
    expanded = [value for argument in arguments for value in (
        parity_modules if argument == "${parity_tests[@]}" else [argument]
    )]
    collected = subprocess.run(  # noqa: S603 - collection-only pytest arguments from the checked-in workflow
        [sys.executable, "-m", "pytest", *expanded, "--collect-only", "-o", "addopts="],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=180,
    )
    output = collected.stdout + collected.stderr
    assert collected.returncode == 0, output
    nodes = {line for line in collected.stdout.splitlines() if line.startswith("tests/") and "::" in line}
    selected_modules = {node.split("::", 1)[0] for node in nodes}
    declared_modules = {argument for argument in expanded if argument.startswith("tests/")}
    assert selected_modules == declared_modules, output
    assert "deselected" not in output, output
    assert {
        "tests/test_postgres_foundation.py::test_live_postgres_rls_hides_other_tenants",
        "tests/test_postgres_finance_core.py::test_live_postgres_finance_core_lifecycle_exactness_and_rls",
        "tests/test_api_server_finance_core_live.py::test_live_server_finance_core_api_routes_are_workspace_scoped_and_lifecycle_exact",
        "tests/test_postgres_inventory_core.py::test_live_postgres_inventory_lifecycle_stock_controls_and_rls",
        "tests/test_alembic_postgres.py::test_alembic_upgrade_command_is_available_when_server_extra_is_installed",
    } <= nodes
