"""Controlled router HTTP with real native ordinary role; no socket TLS claim."""

import hashlib
import json

from fastapi.testclient import TestClient

from reconforge.api.routes.project_source_reconciliation import router
from tests.test_postgres_people_project_payroll_api import application, sessions
from tests.test_postgres_project_source_reconciliation import completed_pair
from tests.test_postgres_project_time_billing import PeopleRuntime

pytest_plugins = ("tests.test_postgres_project_time_billing",)
ROOT = "/api/v1/project-source-reconciliation"


def test_actual_ordinary_http_report_raw_evidence_foreign_scope_and_missing_selection(billing: PeopleRuntime, tmp_path):
    wage, invoice, project = completed_pair(billing)
    app = application(billing, tmp_path, private=False)
    if ROOT + "/report" not in app.openapi()["paths"]:
        app.include_router(router, prefix="/api/v1")
    # The owned router is mounted explicitly for this contract. Central root
    # critical-route registration is a separate integrated gate.
    with TestClient(app, base_url="https://testserver") as client:
        headers = sessions(client, billing)["maker"]
        params = {"payrun_id": wage, "invoice_id": invoice, "project_id": project, "period_id": "period"}
        report = client.get(ROOT + "/report", params=params, headers=headers)
        assert report.status_code == 200, report.text
        assert report.json()["report"]["project_totals"]["source_margin_minor"] == "1267"
        export = client.get(ROOT + "/evidence", params=params, headers=headers)
        assert export.status_code == 200, export.text
        proof = json.loads(export.content)
        assert int(export.headers["content-length"]) == len(export.content)
        assert export.headers["x-reconforge-evidence-digest"] == proof["evidence_digest"]
        assert export.headers["x-reconforge-report-digest"] == report.json()["report"]["report_digest"]
        assert len(proof["original_rows"]["effects"]) == 6 and proof["private_personnel_reads"] is False
        assert (
            client.get(ROOT + "/report", params={**params, "project_id": "foreign"}, headers=headers).status_code == 409
        )
        assert (
            client.get(
                ROOT + "/report", params=params, headers={**headers, "X-ReconForge-Workspace": "foreign"}
            ).status_code
            == 403
        )
        assert export.headers["x-reconforge-raw-sha256"] == hashlib.sha256(export.content).hexdigest()
