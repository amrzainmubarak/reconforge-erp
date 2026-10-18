"""Derived read diagnostics over retained original source rows; no DB claim."""

import copy
import json
from pathlib import Path

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.people_project_payroll import PeopleScope
from reconforge.domain.project_source_reconciliation import ProjectSourceSelection, diagnose_project_source_close


def original():
    return json.loads((Path(__file__).parent / "fixtures/project_source_reconciliation_original_golden_v2.json").read_bytes())


def selected(proof):
    return ProjectSourceSelection(**{**proof["selection"], "scope": PeopleScope(**proof["selection"]["scope"])})


def periods(proof, status="Open"):
    return [{"tenant_id": proof["report"]["qualified_scope"]["tenant_id"],
             "id": proof["selection"]["period_id"],
             "application_workspace_id": proof["report"]["qualified_scope"]["workspace_id"],
             "name": "Synthetic observed period", "start_date": "2026-10-01", "end_date": "2026-10-31",
             "status": status, "updated_at": "2026-10-31T12:00:00+00:00"}]


@pytest.mark.parametrize("status", ["Open", "Soft Closed", "Closed"])
def test_selected_source_obligations_and_claims_are_independent_from_observed_close_status(status):
    proof = original()
    before = copy.deepcopy(proof)
    value = diagnose_project_source_close(selected(proof), proof, periods(proof, status))
    assert value["project_totals"] == {"wage_cost_minor": "1268", "revenue_minor": "2535", "source_margin_minor": "1267"}
    assert value["whole_source_obligations"]["wage_accrued_minor"] == "2501"
    assert value["whole_source_obligations"]["invoice_minor"] == "6236"
    assert value["source_obligations_settled"] is True and value["findings"] == []
    assert len(value["whole_time_claims"]) == 2
    assert all(row["wage_claim"]["state"] == row["billing_claim"]["state"] == "Consumed" for row in value["whole_time_claims"])
    assert value["observed_native_periods"][0]["status"] == status
    assert value["limitations"]["formal_close_workflow_assessed"] is False
    assert value["limitations"]["per_project_cash_allocated"] is False
    assert proof == before


def test_unchanged_original_source_and_period_state_has_stable_diagnostic_across_capture_timestamps():
    from reconforge.application.accrual_deferral_evidence import evidence_digest

    proof = original()
    first = diagnose_project_source_close(selected(proof), proof, periods(proof))
    proof["original_rows"]["captured_at"] = "2026-10-31T12:00:01+00:00"
    proof["evidence_digest"] = evidence_digest({k: v for k, v in proof.items() if k != "evidence_digest"})
    assert diagnose_project_source_close(selected(proof), proof, periods(proof)) == first


@pytest.mark.parametrize("attack", ["missing", "extra", "duplicate", "tenant", "workspace", "id", "status", "dates", "field", "bad_date"])
def test_observed_period_population_is_exact_scoped_and_covers_original_postings(attack):
    proof = original()
    observed = periods(proof)
    if attack == "missing":
        observed = []
    elif attack == "extra":
        observed.append({**observed[0], "id": "unrelated"})
    elif attack == "duplicate":
        observed.append(dict(observed[0]))
    elif attack == "tenant":
        observed[0]["tenant_id"] = "foreign"
    elif attack == "workspace":
        observed[0]["application_workspace_id"] = "foreign"
    elif attack == "id":
        observed[0]["id"] = "foreign"
    elif attack == "field":
        observed[0]["employee_id"] = "private-field-not-in-native-projection"
    elif attack == "bad_date":
        observed[0]["start_date"] = "2026-13-01"
    elif attack == "status":
        observed[0]["status"] = "Ready"
    else:
        observed[0]["end_date"] = "2026-10-02"
    with pytest.raises(FinancePostingError):
        diagnose_project_source_close(selected(proof), proof, observed)


@pytest.mark.parametrize("attack", ["source_report", "native_effect", "missing_time", "duplicate_claim", "foreign_claim", "unposted", "private"])
def test_derivative_requires_original_complete_source_claim_and_native_membership(attack):
    proof = original()
    observed = periods(proof)
    if attack == "source_report":
        proof["report"]["whole_source_settlement"]["collected_minor"] = "0"
    elif attack == "native_effect":
        proof["original_rows"]["effects"].pop()
    elif attack == "missing_time":
        proof["original_rows"]["times"].pop()
    elif attack == "duplicate_claim":
        proof["original_rows"]["hc_claim_heads"].append(dict(proof["original_rows"]["hc_claim_heads"][0]))
    elif attack == "foreign_claim":
        proof["original_rows"]["pb_claim_heads"][0]["invoice_id"] = "PB1-FOREIGN"
    elif attack == "unposted":
        proof["original_rows"]["payruns"][0]["phase"] = 1
    else:
        proof["private_personnel_reads"] = True
    with pytest.raises(FinancePostingError):
        diagnose_project_source_close(selected(proof), proof, observed)
