"""One actual governed partial/final source lifecycle; no socket-TLS claim."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_project_source_reconciliation import (
    PostgresProjectSourceReconciliationRepository,
)
from tests.test_postgres_people_project_payroll import approved_budget, commit
from tests.test_postgres_people_project_payroll import prepare as prepare_wage
from tests.test_postgres_people_project_payroll_api import application, sessions
from tests.test_postgres_project_source_reconciliation import collection, selection
from tests.test_postgres_project_time_billing import PeopleRuntime, post, prepare, sources
from tests.test_postgres_project_time_billing_read_authority import ceiling

pytest_plugins = ("tests.test_postgres_project_time_billing",)
ROOT = Path(__file__).resolve().parents[1]


def independently_verify(proof, label):
    directory = ROOT / "output/project-source-close-native"
    directory.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf8")
    original = directory / (label + "-" + uuid4().hex + ".json")
    with original.open("xb") as handle:
        handle.write(raw)
    outputs = []
    for optimized in (False, True):
        output = directory / (original.stem + ("-IO.json" if optimized else "-I.json"))
        process = subprocess.run([sys.executable, "-I", *(["-O"] if optimized else []),
            str(ROOT / ".github/scripts/verify_project_source_reconciliation.py"), "--kind", "close", "--evidence", str(original),
            "--expected-sha256", hashlib.sha256(raw).hexdigest(), "--output", str(output)], capture_output=True, timeout=30)
        assert process.returncode == 0, process.stderr.decode("utf8", errors="replace")
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]
    return json.loads(outputs[0])


def test_actual_partial_then_final_original_claim_obligations_ordinary_http_and_current_authority(billing: PeopleRuntime, tmp_path, monkeypatch):
    times, prices = sources(billing)
    wage = prepare_wage(billing, times, approved_budget(billing), "close-wage")
    invoice = prepare(billing, times, prices, "close-invoice")
    commit(billing, wage, "close-wage")
    post(billing, invoice, "close-invoice")
    with billing.actor("maker") as (_, repository, actor):
        employees = repository.evidence(wage["id"], actor=actor)["payrun"]["private"]["employees"]
        first = next(row["employee_id"] for row in employees if row["gross_minor"] == 1502)
        second = next(row["employee_id"] for row in employees if row["gross_minor"] == 999)
        partial = repository.prepare_payment(wage["id"], employees_minor={first: 1000}, period_id="period",
            posting_date="2026-10-05", command_id="close-partial-wages", actor=actor)
    commit(billing, partial, "close-partial-wages")
    post(billing, collection(billing, invoice, 1000, "close-partial-ar"), "close-partial-ar")
    with billing.actor("maker", private=False) as (connection, _, actor):
        project = connection.execute("SELECT id FROM reconforge.hc_projects WHERE tenant_id=%s AND project_code='P1'", (billing.base.tenant,)).fetchone()["id"]
        selected = selection((wage["id"], invoice["id"], project))
        count = connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (billing.base.tenant,)).fetchone()["n"]
        value = PostgresProjectSourceReconciliationRepository(connection, billing.base.tenant).close_diagnostics(selected, actor=actor)
        assert value["diagnostic"]["source_obligations_settled"] is False
        assert value["diagnostic"]["findings"] == ["selected_payrun_wages_outstanding", "selected_invoice_receivable_outstanding"]
        assert value["diagnostic"]["whole_source_obligations"]["wage_liability_minor"] == "1501"
        assert value["diagnostic"]["whole_source_obligations"]["ar_outstanding_minor"] == "5236"
        assert count == connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (billing.base.tenant,)).fetchone()["n"] == 4
        assert value["source_evidence"]["original_rows"]["native_role"]["personnel_member"] is False
    assert independently_verify(value, "partial")["source_effect_count"] == 4
    app = application(billing, tmp_path, private=False)
    api = "/api/v1/project-source-reconciliation/close-diagnostics"
    assert {api, api + "/evidence"} <= set(app.openapi()["paths"])
    with TestClient(app, base_url="https://testserver") as client:
        headers = sessions(client, billing)["maker"]
        params = {"payrun_id": wage["id"], "invoice_id": invoice["id"], "project_id": project, "period_id": "period"}
        summary = client.get(api, headers=headers, params=params)
        assert summary.status_code == 200, summary.text
        retained = client.get(api + "/evidence", headers=headers, params=params)
        assert retained.status_code == 200, retained.text
        assert retained.headers["x-reconforge-diagnostic-digest"] == summary.json()["diagnostic"]["diagnostic_digest"]
        assert retained.headers["x-reconforge-raw-sha256"] == hashlib.sha256(retained.content).hexdigest()
        assert int(retained.headers["content-length"]) == len(retained.content)
    with billing.actor("maker") as (_, repository, actor):
        final = repository.prepare_payment(wage["id"], employees_minor={first: 502, second: 999}, period_id="period",
            posting_date="2026-10-06", command_id="close-final-wages", actor=actor)
    commit(billing, final, "close-final-wages")
    post(billing, collection(billing, invoice, 5236, "close-final-ar"), "close-final-ar")
    with billing.actor("maker", private=False) as (connection, _, actor):
        repository = PostgresProjectSourceReconciliationRepository(connection, billing.base.tenant)
        final_value = repository.close_diagnostics(selected, actor=actor)
        repeated = repository.close_diagnostics(selected, actor=actor)
        assert final_value["diagnostic"] == repeated["diagnostic"]
        assert final_value["diagnostic"]["source_obligations_settled"] is True
        assert final_value["diagnostic"]["whole_source_obligations"]["wage_liability_minor"] == "0"
        assert final_value["diagnostic"]["whole_source_obligations"]["ar_outstanding_minor"] == "0"
        assert final_value["diagnostic"]["observed_native_periods"][0]["status"] == "Open"
        assert final_value["diagnostic"]["limitations"]["formal_close_workflow_assessed"] is False
    assert independently_verify(final_value, "final")["source_effect_count"] == 6
    for permission in ("finance_core.read", "people_project_payroll.read", "project_time_billing.read", "receivables.read"):
        with monkeypatch.context() as context:
            seen = ceiling(context, permission)
            with billing.actor("maker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError):
                PostgresProjectSourceReconciliationRepository(connection, billing.base.tenant).close_diagnostics(selected, actor=actor)
            assert seen
    with billing.actor("maker", private=False) as (connection, _, actor):
        with psycopg.connect(billing.base.admin_dsn) as admin:
            admin.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,
                revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change'
                WHERE tenant_id=%s AND permission_name='finance_core.read'""", (billing.base.tenant,))
        with pytest.raises(FinancePostingError) as denied:
            PostgresProjectSourceReconciliationRepository(connection, billing.base.tenant).close_diagnostics(selected, actor=actor)
        assert "denied" in denied.value.code
