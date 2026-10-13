"""Pure diagnostic checks use one byte-exact historical synthetic native source."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from reconforge.application.accrual_deferral_evidence import evidence_digest
from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.intercompany_cashflow import SourceCashOpening
from reconforge.domain.intercompany_group_diagnostic import (
    IntercompanyDiagnosticSelection,
    IntercompanyReportPin,
    reconcile_intercompany_reports,
)


def fixture():
    raw = Path(__file__).with_name("fixtures").joinpath("intercompany-source-cashflow-native-v1.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "00afc06b175e4fd3958624c058db8f28acd798b4d4a852cd7cc968de2fd2cb3b"
    proof = json.loads(raw)
    final = proof["stages"][-1]["plan"]
    selection = IntercompanyDiagnosticSelection((IntercompanyReportPin(SourceCashOpening(**proof["opening"]),
        final["id"], final["plan_digest"], proof["report"]["report_digest"]),))
    # Status observations below are pure planned metadata, not a new DB receipt.
    periods = [{"id": "period", "tenant_id": proof["qualified_scope"]["tenant_id"], "application_workspace_id": "work",
                "status": "Open", "start_date": "2026-10-01", "end_date": "2026-10-31"}]
    return selection, [proof], periods


def test_original_reporting_cash_bridge_is_not_a_native_adjustment_cash_claim():
    result = reconcile_intercompany_reports(*fixture())
    rows = {row["role"]: row for row in result["trial_balance_bridge"]}
    assert rows["cash"]["translated_minor"] == rows["cash"]["combined_minor"] == 101
    assert rows["cash"]["native_adjustment_minor"] == 0
    assert result["income_statement"] == {"income_minor": 563, "expense_minor": 171, "result_minor": 392}
    assert result["balance_sheet"]["equity_minor"] == -291
    assert result["formal_close_workflow_assessed"] is result["whole_group_membership_proven"] is False
    assert result["diagnostic_digest"] == digest_payload({key: value for key, value in result.items() if key != "diagnostic_digest"})


@pytest.mark.parametrize("status", ["Open", "Soft Closed", "Closed"])
def test_observed_native_period_status_does_not_change_formal_workflow_qualification(status):
    selection, proofs, periods = fixture()
    periods[0]["status"] = status
    result = reconcile_intercompany_reports(selection, proofs, periods)
    assert result["native_period_observations"][0]["status"] == status
    assert result["source_elimination_complete"] is True and result["formal_close_workflow_assessed"] is False


@pytest.mark.parametrize("field", ["report_digest", "elimination_plan_digest", "elimination_plan_id"])
def test_stale_original_pins_refuse_even_a_complete_balanced_source(field):
    selection, proofs, periods = fixture()
    pin = replace(selection.pins[0], **{field: "0" * 64 if field.endswith("digest") else "IC2E-other"})
    with pytest.raises(FinancePostingError, match="seal differs"):
        reconcile_intercompany_reports(IntercompanyDiagnosticSelection((pin,)), proofs, periods)


@pytest.mark.parametrize("mutation", ["missing", "extra", "tenant", "workspace", "date", "status"])
def test_exact_scoped_period_population_and_date_membership(mutation):
    selection, proofs, periods = fixture()
    if mutation == "missing":
        periods.clear()
    elif mutation == "extra":
        periods.append({**periods[0], "id": "unrelated"})
    else:
        periods[0].update({"tenant": {"tenant_id": "foreign"}, "workspace": {"application_workspace_id": "foreign"},
                          "date": {"end_date": "2026-10-02"}, "status": {"status": "Unknown"}}[mutation])
    with pytest.raises(FinancePostingError, match="period"):
        reconcile_intercompany_reports(selection, proofs, periods)


def test_duplicate_selected_source_cannot_double_the_same_native_effects():
    selection, _, _ = fixture()
    with pytest.raises(FinancePostingError, match="unique"):
        IntercompanyDiagnosticSelection(selection.pins * 2)


@pytest.mark.parametrize("mutation", ["tenant", "workspace", "entity"])
def test_qualified_capture_cannot_relabel_original_native_source_hierarchy(mutation):
    selection, proofs, periods = fixture()
    if mutation == "tenant":
        proofs[0]["qualified_scope"]["tenant_id"] = periods[0]["tenant_id"] = "foreign"
    elif mutation == "workspace":
        proofs[0]["qualified_scope"]["workspace_id"] = periods[0]["application_workspace_id"] = "foreign"
    else:
        proofs[0]["qualified_scope"]["legal_entity_ids"]["buyer"] = "foreign"
    with pytest.raises(FinancePostingError, match="hierarchy"):
        reconcile_intercompany_reports(selection, proofs, periods)


def test_rehashed_balanced_report_cannot_invent_an_adjustment_cash_bridge():
    selection, proofs, periods = fixture()
    proof = proofs[0]
    cash = next(row for row in proof["report"]["trial_balance"] if row["role"] == "cash")
    cash["native_adjustment_membership"] = [{"account_code": cash["account_code"], "debit_minor": 1, "credit_minor": 0}]
    proof["report"]["report_digest"] = digest_payload({key: value for key, value in proof["report"].items() if key != "report_digest"})
    proof["cashflow"]["report_digest"] = proof["report"]["report_digest"]
    proof["cashflow"]["cashflow_digest"] = digest_payload({key: value for key, value in proof["cashflow"].items() if key != "cashflow_digest"})
    proof["evidence_digest"] = evidence_digest({key: value for key, value in proof.items() if key != "evidence_digest"})
    pin = replace(selection.pins[0], report_digest=proof["report"]["report_digest"])
    with pytest.raises(FinancePostingError, match="retained report"):
        reconcile_intercompany_reports(IntercompanyDiagnosticSelection((pin,)), proofs, periods)


def test_diagnostic_preserves_all_original_source_bytes_and_input_metadata():
    selection, proofs, periods = fixture()
    before = deepcopy((proofs, periods))
    reconcile_intercompany_reports(selection, proofs, periods)
    assert (proofs, periods) == before
