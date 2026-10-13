"""Authenticated TestClient reads and bounded original downloads; no wire claim."""

import hashlib
from pathlib import Path

from reconforge.domain.finance_posting import digest_payload
from reconforge.infrastructure.postgres_intercompany_cashflow import PostgresIntercompanyCashflowRepository
from tests.test_postgres_intercompany_cashflow import opening, write_original
from tests.test_postgres_intercompany_fx import FxRuntime, cash, eliminate, recognize, revalue
from tests.test_postgres_intercompany_fx_api import client, intercompany_fx_database, receipt_database, runtime

__all__ = ["runtime", "intercompany_fx_database", "receipt_database"]
pytest_plugins = ("tests.test_postgres_intercompany_fx",)
ROOT = "/api/v1/intercompany-source-cashflow/sources/"


def parameters(rt, original):
    captured = opening(rt, original)
    return {"source_digest": captured.source_digest, "origin_plan_id": captured.origin_plan_id,
        "origin_plan_digest": captured.origin_plan_digest, "seller_opening_minor": "0", "buyer_opening_minor": "0",
        "opening_basis": captured.basis}


def financial_population(connection, tenant):
    from psycopg import sql

    # Existing HTTP authorization appends policy evaluation audit/outbox events. Keep
    # every business/source/native table byte-exact, and separately compare the
    # exact original source audit/outbox membership captured by the reader.
    tables = ("intercompany_fx_sources", "intercompany_fx_plans", "intercompany_fx_reviews", "intercompany_fx_links",
        "intercompany_fx_post_evidence", "intercompany_fx_commands", "finance_entries", "finance_entry_lines",
        "finance_entry_line_dimensions", "finance_posting_effects", "finance_posting_commands")
    return digest_payload({table: [row["payload"] for row in connection.execute(sql.SQL(
        "SELECT to_jsonb(t) payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text"
    ).format(sql.Identifier(table)), (tenant,))] for table in tables})


def test_actual_authenticated_view_and_original_export_require_explicit_opening_and_preserve_gl(runtime: FxRuntime,
        intercompany_fx_database: tuple[str, str], tmp_path: Path) -> None:
    original = recognize(runtime)
    basis = opening(runtime, original)
    params = parameters(runtime, original)
    cash(runtime, original["source_id"])
    revalue(runtime, original["source_id"])
    eliminate(runtime, original["source_id"])
    with client(runtime, intercompany_fx_database, tmp_path, "poster", step_up=False) as (session, headers):
        assert ROOT + "{source_id}" in session.app.openapi()["paths"]
        # client_for first provisions its unrelated original entity grant and
        # audit event. Capture the baseline after that setup, before any view.
        with runtime.actor("poster") as (connection, _, actor):
            before = financial_population(connection, runtime.base.tenant)
            original_capture = PostgresIntercompanyCashflowRepository(connection, runtime.base.tenant).evidence(
                original["source_id"], opening=basis, actor=actor)
            before_audit = {row["id"]: row["action"] for row in connection.execute(
                "SELECT id,action FROM reconforge.domain_audit_events WHERE tenant_id=%s", (runtime.base.tenant,))}
        path = ROOT + original["source_id"]
        assert session.get(path, headers=headers).status_code == 422
        assert session.get(path, params={**params, "seller_opening_minor": "1"}, headers=headers).status_code == 400
        assert session.get(path, params={**params, "opening_basis": "unknown"}, headers=headers).status_code == 400
        assert session.get(path, params={**params, "unexpected": "field"}, headers=headers).status_code == 422
        assert session.get(path, params=params, headers={**headers, "X-ReconForge-Legal-Entity": "seller"}).status_code == 403
        result = session.get(path, params=params, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["cashflow"]["operating_net_minor"] == "0"
        assert result.json()["cashflow"]["fx_on_cash_minor"] == result.json()["cashflow"]["closing_minor"] == "101"
        assert result.json()["qualified_scope"] == original_capture["qualified_scope"]
        export = session.get(path + "/evidence/export", params=params, headers=headers)
        assert export.status_code == 200, export.text
        assert int(export.headers["content-length"]) == len(export.content)
        assert export.headers["X-ReconForge-Evidence-SHA256"] == hashlib.sha256(export.content).hexdigest()
        assert result.json()["evidence_sha256"] == hashlib.sha256(export.content).hexdigest()
        assert result.json()["evidence_bytes"] == len(export.content)
        proof = export.json()
        assert proof == original_capture
        assert proof["cashflow"]["cashflow_digest"] == result.json()["cashflow"]["cashflow_digest"]
        assert proof["qualified_scope"]["tenant_id"] == runtime.base.tenant
        assert len(proof["original_rows"]["effects"]) == 7
        write_original(proof)
    with runtime.actor("poster") as (connection, _, _):
        assert financial_population(connection, runtime.base.tenant) == before
        after_audit = {row["id"]: row["action"] for row in connection.execute(
            "SELECT id,action FROM reconforge.domain_audit_events WHERE tenant_id=%s", (runtime.base.tenant,))}
        assert all(after_audit[key] == action for key, action in before_audit.items())
        print("API appended audit actions:", sorted(action for key, action in after_audit.items() if key not in before_audit))


def test_actual_cached_api_reader_refuses_withdrawn_original_group_authority(runtime: FxRuntime,
        intercompany_fx_database: tuple[str, str], tmp_path: Path) -> None:
    import psycopg

    original = recognize(runtime)
    params = parameters(runtime, original)
    cash(runtime, original["source_id"])
    revalue(runtime, original["source_id"])
    eliminate(runtime, original["source_id"])
    with client(runtime, intercompany_fx_database, tmp_path, "poster", step_up=False) as (session, headers):
        assert ROOT + "{source_id}/evidence/export" in session.app.openapi()["paths"]
        path = ROOT + original["source_id"]
        assert session.get(path, params=params, headers=headers).status_code == 200
        with psycopg.connect(runtime.base.admin_dsn) as admin:
            admin.execute("""UPDATE reconforge.principal_scope_grants SET revoked_at=now(),revoked_by='maker',
                revocation_reason='Withdraw cashflow original group evidence access' WHERE tenant_id=%s AND principal_id='poster'
                AND scope_type='legal_entity' AND scope_id='group'""", (runtime.base.tenant,))
        assert session.get(path, params=params, headers=headers).status_code == 403
        assert session.get(path + "/evidence/export", params=params, headers=headers).status_code == 403
