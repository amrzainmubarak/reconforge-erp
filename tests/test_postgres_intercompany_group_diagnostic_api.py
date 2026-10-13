"""Actual ordinary authenticated native diagnostic and byte-exact export."""

import hashlib
import json
from dataclasses import asdict

from reconforge.api.routes.intercompany_group_diagnostic import router
from reconforge.infrastructure.postgres_intercompany_group_diagnostic import (
    PostgresIntercompanyGroupDiagnosticRepository,
)
from tests.test_postgres_intercompany_cashflow_api import financial_population
from tests.test_postgres_intercompany_fx_api import client
from tests.test_postgres_intercompany_group_diagnostic import closed_source, selection, write_original

pytest_plugins = ("tests.test_postgres_intercompany_fx",)


def test_ordinary_authenticated_diagnostic_report_and_original_export_retain_every_original_source(runtime,
                                                                                               intercompany_fx_database, tmp_path):
    chosen = selection(closed_source(runtime, "authenticated"))
    with client(runtime, intercompany_fx_database, tmp_path, "poster", step_up=False) as (session, headers):
        session.app.include_router(router, prefix="/api/v1")
        with runtime.actor("poster") as (connection, _, actor):
            before = financial_population(connection, runtime.base.tenant)
            original = PostgresIntercompanyGroupDiagnosticRepository(connection, runtime.base.tenant).evidence(chosen, actor=actor)
        params = {"selection": json.dumps(asdict(chosen), sort_keys=True, separators=(",", ":"))}
        viewed = session.get("/api/v1/intercompany-group-diagnostic/report", params=params, headers=headers)
        assert viewed.status_code == 200, viewed.text
        report = viewed.json()
        assert report["diagnostic"]["cash_equation"]["closing_minor"] == "101"
        assert report["diagnostic"]["whole_group_membership_proven"] is False
        exported = session.get("/api/v1/intercompany-group-diagnostic/evidence", params=params, headers=headers)
        assert exported.status_code == 200, exported.text
        assert len(exported.content) == report["evidence_bytes"] == int(exported.headers["Content-Length"])
        assert hashlib.sha256(exported.content).hexdigest() == report["evidence_sha256"] == exported.headers["X-ReconForge-Evidence-SHA256"]
        assert exported.json() == original
        assert session.get("/api/v1/intercompany-group-diagnostic/report", headers=headers).status_code == 422
        assert session.get("/api/v1/intercompany-group-diagnostic/evidence", params={"selection": "{}"}, headers=headers).status_code == 400
        with runtime.actor("poster") as (connection, _, actor):
            assert financial_population(connection, runtime.base.tenant) == before
            assert PostgresIntercompanyGroupDiagnosticRepository(connection, runtime.base.tenant).evidence(chosen, actor=actor) == original
        write_original(original)
