from __future__ import annotations

import importlib.util
import inspect
import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.consolidation_close import (
    ConsolidationCloseRepositoryProtocol,
    build_translation_evidence,
)
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, set_local_tenant_scope
from reconforge.infrastructure.postgres_consolidation_close import (
    POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL,
    PostgresConsolidationCloseRepository,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_consolidation_close_schema_is_tenant_scoped_and_exact() -> None:
    schema = POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL
    assert "JSONB NOT NULL" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "current_setting(''app.tenant_id'',true)" in schema
    assert "consolidation_close_run_lines" in schema
    assert "consolidation_close_effect_lines" in schema
    assert "append-only" in schema
    assert "DOUBLE PRECISION" not in schema


def test_postgres_consolidation_close_migration_is_linear_and_reversible() -> None:
    path = ROOT / "alembic/versions/0055_postgres_consolidation_close.py"
    spec = importlib.util.spec_from_file_location("migration_0055", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0055_pg_consol_close"
    assert module.down_revision == "0054_pg_consol_ownership"
    assert "DROP TABLE IF EXISTS reconforge.consolidation_close_runs" in path.read_text(encoding="utf-8")


def test_postgres_consolidation_journal_lines_migration_is_linear_and_reversible() -> None:
    path = ROOT / "alembic/versions/0057_postgres_consolidation_journal_lines.py"
    spec = importlib.util.spec_from_file_location("migration_0057", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0057_pg_consol_journal_lines"
    assert module.down_revision == "0056_pg_policy_delegations"
    sql = path.read_text(encoding="utf-8")
    assert "journal_line_count" in sql
    assert "DROP TABLE IF EXISTS reconforge.consolidation_close_effect_lines" in sql


def test_postgres_adapter_exposes_the_backend_neutral_close_port() -> None:
    required = {
        name
        for name, value in vars(ConsolidationCloseRepositoryProtocol).items()
        if callable(value) and not name.startswith("__")
    }
    assert required <= set(vars(PostgresConsolidationCloseRepository))
    for name in required:
        assert callable(getattr(PostgresConsolidationCloseRepository, name))
        assert (
            inspect.signature(getattr(PostgresConsolidationCloseRepository, name)).return_annotation
            is not inspect.Signature.empty
        )


def test_postgres_journal_material_is_canonical_and_balanced() -> None:
    from tests.test_sqlite_consolidation_close import _worksheet

    lines, digest = PostgresConsolidationCloseRepository._worksheet_lines(_worksheet())
    assert len(lines) == 2
    assert sum(line["amount_minor"] for line in lines) == 0
    assert {line["amount_decimal"] for line in lines} == {"12.00", "-12.00"}
    assert len(digest) == 64
    restored = PostgresConsolidationCloseRepository._line_material(
        {
            "account_type": "Asset",
            "amount_decimal": "999.000000",
            "amount_minor": 1200,
            "currency_code": "USD",
            "elimination_id": "ELIM-IC-1",
            "entity_code": "SUB",
            "group_account_code": "1000",
            "source_digest": "source",
            "source_line_id": "line",
            "source_reference": "reference",
        }
    )
    assert restored["amount_decimal"] == "12.00"
    assert PostgresConsolidationCloseRepository._amount_matches_minor("12.000000000000000000", 1200, "USD")
    assert not PostgresConsolidationCloseRepository._amount_matches_minor("12.01", 1200, "USD")


def test_translation_evidence_projection_is_backend_neutral() -> None:
    from tests.test_sqlite_consolidation_close import _worksheet

    worksheet = _worksheet()
    evidence = build_translation_evidence(worksheet.request.translation_result).to_dict()

    assert evidence["result_digest"] == worksheet.translation_result_digest
    assert evidence["line_count"] == 4
    assert evidence["source_currencies"] == ["USD"]
    assert len(str(evidence["lineage_digest"])) == 64


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL application role",
)
def test_live_postgres_consolidation_close_is_tenant_isolated_and_replayable() -> None:
    psycopg = pytest.importorskip("psycopg")
    from tests.test_sqlite_consolidation_close import _worksheet

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    tenant_a = "pgclose_a_" + uuid4().hex[:10]
    tenant_b = "pgclose_b_" + uuid4().hex[:10]
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.consolidation_close_periods,"
                " reconforge.consolidation_close_runs,reconforge.consolidation_close_effects,"
                " reconforge.consolidation_close_period_events,reconforge.consolidation_close_run_lines,"
                " reconforge.consolidation_close_effect_lines,reconforge.certification_records TO " + app_user
            )
            admin.execute(
                "GRANT SELECT,INSERT,UPDATE ON reconforge.domain_audit_ledger_state,"
                " reconforge.domain_audit_events,reconforge.outbox_events TO " + app_user
            )
    finally:
        admin.close()

    connection = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False)).connect()
    try:
        repository = PostgresConsolidationCloseRepository(connection, tenant_a)
        worksheet = _worksheet()
        period = repository.create_period(
            group_code=worksheet.group_code,
            period_id=worksheet.period_id,
            reporting_currency=worksheet.reporting_currency,
            period_start_date=worksheet.period_start_date,
            period_end_date=worksheet.period_end_date,
            reporting_date=worksheet.reporting_date,
            workspace="close",
            actor_label="period-preparer",
        )
        first = repository.prepare_run(
            run_number="RUN-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        replay = repository.prepare_run(
            run_number="RUN-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        assert first["id"] == replay["id"]
        approved = repository.approve_run(
            first["id"], expected_version=1, reason="reviewed", actor_label="close-reviewer"
        )
        posted = repository.post_run(
            first["id"], expected_version=approved["row_version"], reason="posted", actor_label="close-poster"
        )
        prepared_certification = repository.prepare_certification(
            posted["id"], note="Posted control-journal evidence prepared.", actor_label="close-certifier"
        )
        assert prepared_certification["status"] == "Prepared"
        with pytest.raises(PlatformError, match="different"):
            repository.review_certification(posted["id"], note="Self review", actor_label="close-certifier")
        reviewed_certification = repository.review_certification(
            posted["id"], note="Independent certification review.", actor_label="close-cert-reviewer"
        )
        assert reviewed_certification["status"] == "Reviewed"
        assert repository.get_certification(posted["id"])["reviewed_by"] == "close-cert-reviewer"
        reversal = repository.request_reversal(
            first["id"],
            expected_version=posted["row_version"],
            reason="correcting",
            actor_label="reversal-preparer",
        )
        repository.approve_reversal(
            first["id"],
            expected_version=reversal["row_version"],
            reason="approved",
            actor_label="reversal-reviewer",
        )
        locked = repository.lock_period(period["id"], expected_version=1, reason="close", actor_label="period-reviewer")
        assert locked["status"] == "Locked"
        with pytest.raises(PlatformError, match="independent"):
            repository.reopen_period(
                period["id"],
                expected_version=locked["row_version"],
                reason="same actor",
                actor_label="period-reviewer",
            )
        reopened = repository.reopen_period(
            period["id"],
            expected_version=locked["row_version"],
            reason="controlled reopen",
            actor_label="period-reopener",
        )
        assert reopened["status"] == "Open"
        assert repository.summary(workspace="close").reversed_runs == 1
        detail = repository.get_run(first["id"])
        assert detail["worksheet"]["worksheet_id"] == worksheet.worksheet_id
        assert len(detail["journal_lines"]) == 2
        assert {str(line["currency_code"]) for line in detail["journal_lines"]} == {"USD"}
        assert {str(effect["effect_type"]) for effect in detail["effects"]} == {"Posting", "Reversal"}
        assert all(str(effect["status"]) == "Committed" for effect in detail["effects"])
        assert all(len(effect["lines"]) == 2 for effect in detail["effects"])
        with connection.transaction():
            set_local_tenant_scope(connection, tenant_a)
            with pytest.raises(psycopg.Error, match="append-only"):
                connection.execute(
                    "UPDATE reconforge.consolidation_close_run_lines "
                    "SET amount_minor=amount_minor+1 WHERE tenant_id=%s AND run_id=%s",
                    (tenant_a, first["id"]),
                )
        with connection.transaction():
            set_local_tenant_scope(connection, tenant_a)
            events = connection.execute(
                "SELECT action,actor FROM reconforge.consolidation_close_period_events WHERE tenant_id=%s AND period_id=%s ORDER BY created_at,id",
                (tenant_a, period["id"]),
            ).fetchall()
        assert [(str(item["action"]), str(item["actor"])) for item in events] == [
            ("Locked", "period-reviewer"),
            ("Open", "period-reopener"),
        ]
        with pytest.raises(PlatformError, match="not found"):
            PostgresConsolidationCloseRepository(connection, tenant_b).get_period(period["id"])
    finally:
        connection.close()
