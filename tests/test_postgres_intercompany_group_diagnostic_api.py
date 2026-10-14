"""Actual ordinary authenticated native diagnostic and byte-exact export."""

import hashlib
import json
from dataclasses import asdict

from reconforge.domain.finance_posting import canonical_json, digest_payload
from reconforge.infrastructure.postgres_intercompany_group_diagnostic import (
    PostgresIntercompanyGroupDiagnosticRepository,
)
from tests.api_route_registration import registered_http_operations
from tests.test_postgres_intercompany_cashflow_api import financial_population
from tests.test_postgres_intercompany_fx_api import client
from tests.test_postgres_intercompany_group_diagnostic import closed_source, selection, write_original

pytest_plugins = ("tests.test_postgres_intercompany_fx",)


def test_current_native_http_source_plan_projection_preserves_seals_and_distinct_original_phase_effect_proof(
    runtime, intercompany_fx_database, tmp_path,
):
    chosen = selection(closed_source(runtime, "browser-http-projection"))
    source_id = chosen.pins[0].opening.source_id
    def unproject(value, key=""):
        if isinstance(value, dict):
            return {name: unproject(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [unproject(item) for item in value]
        if key == "native_balance_minor" and value is None:
            return None  # CTA is derived; it has no standalone native balance.
        if key.endswith("_minor"):
            assert isinstance(value, str) and value.lstrip("-").isdigit()
            return int(value)
        return value
    with client(runtime, intercompany_fx_database, tmp_path, "poster", step_up=False) as (session, headers):
        response = session.get("/api/v1/intercompany-fx/sources/" + source_id, headers=headers)
        assert response.status_code == 200, response.text
        detail = response.json()["source"]
        assert detail["state"]["closed"] is True and len(detail["plans"]) == 4
        source = {key: value for key, value in detail.items() if key not in {"plans", "state"}}
        assert digest_payload({key: value for key, value in unproject(source).items() if key != "source_digest"}) == source["source_digest"]
        for plan in detail["plans"]:
            assert plan["phase"] == 2 and plan["status"] == "Posted"
            evidence_response = session.get("/api/v1/intercompany-fx/plans/" + plan["id"] + "/evidence", headers=headers)
            assert evidence_response.status_code == 200, evidence_response.text
            evidence = evidence_response.json()["evidence"]
            assert evidence["plan"] == plan and evidence["source"] == source
            assert evidence["canonical_source_json"] == canonical_json({key: value for key, value in unproject(source).items() if key != "source_digest"})
            sealed_plan = {key: value for key, value in unproject(plan).items() if key not in {
                "phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_ids", "plan_digest"}}
            assert canonical_json(sealed_plan) == evidence["canonical_plan_json"]
            assert digest_payload(sealed_plan) == plan["plan_digest"]
            # get_source emits complete immutable plan views, but does not
            # emit these indispensable native effects and three phase events.
            assert "native_effects" not in plan and "phases" not in plan
            assert len(evidence["phases"]) == 3
            assert len({row["actor_id"] for row in evidence["phases"]}) == 3
            assert all(row["audit_event_id"] and row["outbox_event_id"] for row in evidence["phases"])
            assert len(evidence["native_effects"]) == len(plan["entries"])
            effects = {effect["entry_id"]: effect for effect in evidence["native_effects"]}
            for index, entry in enumerate(plan["entries"]):
                snapshot = unproject(entry["snapshot"])
                assert evidence["canonical_snapshot_jsons"][index] == canonical_json(snapshot)
                assert digest_payload(snapshot) == entry["validation_digest"]
                effect = effects[entry["entry_id"]]
                assert effect["snapshot"] == entry["snapshot"] and effect["validation_digest"] == entry["validation_digest"]
                assert effect["posted_actor_id"] == plan["posted_actor_id"]
                assert effect["id"] == plan["posting_effect_ids"][entry["book"]]
                assert effect["audit_event_id"] and effect["outbox_event_id"]
        reread = session.get("/api/v1/intercompany-fx/sources/" + source_id, headers=headers)
        assert reread.status_code == 200 and reread.json()["source"] == detail


def test_ordinary_authenticated_diagnostic_report_and_original_export_retain_every_original_source(runtime,
                                                                                               intercompany_fx_database, tmp_path):
    chosen = selection(closed_source(runtime, "authenticated"))
    with client(runtime, intercompany_fx_database, tmp_path, "poster", step_up=False) as (session, headers):
        registrations = registered_http_operations(session.app)
        assert registrations[("GET", "/api/v1/intercompany-group-diagnostic/report")] == 1
        assert registrations[("GET", "/api/v1/intercompany-group-diagnostic/evidence")] == 1
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
