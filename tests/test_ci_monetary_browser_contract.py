"""Required monetary transport/restore wiring; no database/browser is executed."""
from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from reconforge.infrastructure.postgres_enterprise_modules_schema import (
    REGISTERED_MODULE_TABLES,
    RETAINED_ENTERPRISE_TABLES,
)
from tests.customer_partial_return_monetary_posted_oracle import TABLES
from tests.gfo_browser_restore import FINANCIAL_TABLES

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("monetary_required_browser_runner", ROOT / ".github/scripts/verify_erp_expansion_browser.py")
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_two_fixed_monetary_cases_are_required_browser_matrix_owners_and_preserve_budgets() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["enterprise-browser-recovery"]
    assert RUNNER.MONETARY_SCENARIOS == {"customer-partial-return-monetary-identity": "identity", "customer-partial-return-monetary-foreign": "foreign"}
    for name in RUNNER.MONETARY_SCENARIOS:
        assert job["strategy"]["matrix"]["scenario"].count(name) == 1
    assert job["timeout-minutes"] == 20 and job["strategy"]["max-parallel"] == 3 and job["strategy"]["fail-fast"] is False
    assert "continue-on-error" not in job
    gate = next(step for step in job["steps"] if step["name"] == "Execute enterprise HTTPS cycle and populated native recovery")
    assert "if" not in gate and "--verify-native-restore" in gate["run"]


def restore_metadata() -> dict[str, Any]:
    protected = sorted(set(TABLES) | set(FINANCIAL_TABLES))
    audits = ["domain_audit_events", "domain_audit_ledger_state"]
    new_tables = {"stock_sales_monetary_origins", "customer_partial_return_monetary_commands", "customer_partial_return_monetary_entries",
                  "customer_partial_return_monetary_events", "customer_partial_return_monetary_history", "customer_partial_return_monetary_plans", "customer_partial_return_monetary_restorations"}
    catalog = dict.fromkeys(sorted(new_tables), {})
    catalog.update({"synthetic_catalog_" + str(index): {} for index in range(340)})
    catalog.update(dict.fromkeys(REGISTERED_MODULE_TABLES + RETAINED_ENTERPRISE_TABLES + ("enterprise_finance_bindings", "enterprise_finance_commands", "crm_quotation_authorities", "quality_ncr_actor_authorities"), {}))
    return {"status": "passed", "tamper_refusals": 3, "snapshot": {"head": "0157_pg_quality_actor_authority", "tables": catalog, "forced_rls_financial_tables": 93},
            "protected_financial_tables": protected, "unbound_tenant_probe_tables": protected.copy(),
            "sibling_workspace_probe_tables": sorted(set(TABLES) - set(audits)), "tenant_global_audit_tables": audits,
            "scope_probe_counts": {"protected": 93, "unbound_tenant": 93, "sibling_workspace": 89, "tenant_global_audit": 2}}


def test_raw91_protected93_and_versioned_catalog384_are_distinct_guarded_contracts() -> None:
    assert len(TABLES) == 91 and set(FINANCIAL_TABLES) - set(TABLES) == {"currency_registry_bindings", "currency_registry_snapshots"}
    assert len(restore_metadata()["snapshot"]["tables"]) == 347 + 14 + 19 + 2 + 1 + 1 == 384
    RUNNER.require_monetary_native_restore(restore_metadata())


@pytest.mark.parametrize("damage", ["catalog340", "new-table-absent", "enterprise-table-substituted", "crm-authority-absent", "quality-authority-absent", "prior-head", "prior-crm-head", "prior-hcm-head", "extra-table", "raw91-as-protected", "audit-omitted", "workspace-omitted", "tamper-bool", "count-bool"])
def test_incomplete_or_reclassified_monetary_restore_cannot_pass(damage: str) -> None:
    value = deepcopy(restore_metadata())
    if damage == "catalog340":
        for key in list(value["snapshot"]["tables"])[-7:]:
            del value["snapshot"]["tables"][key]
    elif damage == "new-table-absent":
        del value["snapshot"]["tables"]["stock_sales_monetary_origins"]
        value["snapshot"]["tables"]["unknown_new_table"] = {}
    elif damage == "enterprise-table-substituted":
        del value["snapshot"]["tables"]["enterprise_finance_commands"]
        value["snapshot"]["tables"]["unknown_new_table"] = {}
    elif damage == "prior-head":
        value["snapshot"]["head"] = "0152_pg_performance_indexes"
    elif damage == "prior-crm-head":
        value["snapshot"]["head"] = "0155_pg_crm_authority"
    elif damage == "prior-hcm-head":
        value["snapshot"]["head"] = "0156_pg_hcm_leave_entity"
    elif damage == "crm-authority-absent":
        del value["snapshot"]["tables"]["crm_quotation_authorities"]
        value["snapshot"]["tables"]["unknown_new_table"] = {}
    elif damage == "quality-authority-absent":
        del value["snapshot"]["tables"]["quality_ncr_actor_authorities"]
        value["snapshot"]["tables"]["unknown_new_table"] = {}
    elif damage == "extra-table":
        value["snapshot"]["tables"]["unregistered_table"] = {}
    elif damage == "raw91-as-protected":
        value["protected_financial_tables"] = list(TABLES)
    elif damage == "audit-omitted":
        value["tenant_global_audit_tables"] = []
    elif damage == "workspace-omitted":
        value["sibling_workspace_probe_tables"].pop()
    elif damage == "tamper-bool":
        value["tamper_refusals"] = True
    else:
        value["scope_probe_counts"]["tenant_global_audit"] = True
    with pytest.raises(ValueError):
        RUNNER.require_monetary_native_restore(value)


def test_malformed_monetary_financial_proof_quarantines_publication_before_generic_allowlists(tmp_path: Path) -> None:
    private, public = tmp_path / "private", tmp_path / "public"
    private.mkdir()
    public.mkdir()
    (private / "browser.log").write_text("Synthetic completed browser log\n", encoding="utf-8")
    published = RUNNER.publish_browser_diagnostics(public, private, [], monetary_financial_verification={"status": "passed"}, monetary_case="identity", monetary_require_restore=True)
    assert published["status"] == "quarantined"
    assert RUNNER._public_diagnostic_paths(public) == []
