"""PROD-017: metrics must work after real migrations, without schema installers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from reconforge.application.metrics import MetricsApplicationService
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_metrics import PostgresMetricsRepository
from tests.test_alembic_postgres import isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = "0092_pg_close_lock_evidence"
CURRENT = "0093_pg_metrics"
isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn


def _migration_config() -> Any:
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config


def test_live_clean_migration_installs_metrics_and_empty_downgrade_replays(
    isolated_postgres_migration_dsn: str,
) -> None:
    import psycopg

    from alembic import command

    config = _migration_config()
    command.upgrade(config, PREVIOUS)
    with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
        assert admin.execute("SELECT to_regclass('reconforge.metric_definitions')").fetchone()[0] is None
        command.upgrade(config, CURRENT)
        definitions = admin.execute("SELECT * FROM reconforge.metric_definitions ORDER BY metric_key").fetchall()
        assert len(definitions) == 8
        assert admin.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid='reconforge.metric_snapshots'::regclass"
        ).fetchone() == (True, True)
        command.downgrade(config, PREVIOUS)
        assert admin.execute("SELECT to_regclass('reconforge.metric_snapshots')").fetchone()[0] is None
        command.upgrade(config, CURRENT)
        assert admin.execute("SELECT * FROM reconforge.metric_definitions ORDER BY metric_key").fetchall() == definitions


def test_live_migrated_metrics_compute_replay_isolate_and_refuse_populated_downgrade(
    isolated_postgres_migration_dsn: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg
    from sqlalchemy.engine import URL
    from sqlalchemy.exc import DBAPIError

    from alembic import command

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("PROD-017 live metrics migration gate requires a non-privileged PostgreSQL application DSN")
    parameters = psycopg.conninfo.conninfo_to_dict(app_dsn)
    parameters["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    config = _migration_config()
    command.upgrade(config, CURRENT)
    with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
        role = psycopg.sql.Identifier(parameters["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT INSERT, UPDATE ON reconforge.metric_snapshots TO {}").format(role))
        for tenant in ("metrics_a", "metrics_b"):
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant, tenant))
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name,local_first_note,created_at) "
                "VALUES (%s,'workspace','Metrics','','2026-10-03T00:00:00Z')", (tenant,),
            )
        admin.execute(
            "INSERT INTO reconforge.exception_queue_records "
            "(tenant_id,id,workspace_id,source_type,source_id,risk_rating,description,created_by,last_actor) "
            "VALUES ('metrics_a','exception','workspace','control','source','high','Synthetic finding','operator','operator')"
        )
        factory = PostgresConnectionFactory(PostgresSettings(
            dsn=psycopg.conninfo.make_conninfo(**parameters), require_tls=False,
        ))
        boundary = PostgresTenantBoundary(factory)
        monkeypatch.setattr("reconforge.application.metrics.utc_now_text", lambda: "2026-10-03T00:00:00Z")
        with boundary.transaction("metrics_a") as connection:
            role_flags = connection.execute(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            assert tuple(role_flags) == (False, False)
            service = MetricsApplicationService(PostgresMetricsRepository(connection, "metrics_a"))
            first = service.compute(workspace="Metrics", actor_label="operator")
            assert len(first) == 8
            assert {row["metric_key"]: row["value_text"] for row in first}["unresolved_high_risk_exceptions"] == "1"
            assert service.compute(workspace="Metrics", actor_label="operator") == first
            assert service.dashboard() == first
            assert connection.execute("SELECT count(*) FROM reconforge.metric_snapshots").fetchone()[0] == 8
        with boundary.transaction("metrics_b") as connection:
            assert MetricsApplicationService(PostgresMetricsRepository(connection, "metrics_b")).dashboard() == []
            assert connection.execute("SELECT count(*) FROM reconforge.metric_snapshots").fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege), boundary.transaction("metrics_b") as connection:
            connection.execute(
                "INSERT INTO reconforge.metric_snapshots "
                "(id,tenant_id,workspace_id,metric_key,period_name,value,value_text,lineage,computed_at) "
                "VALUES ('foreign','metrics_a','workspace','match_rate','other',0,'0','synthetic','2026-10-03')"
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege), boundary.transaction("metrics_b") as connection:
            connection.execute("UPDATE reconforge.metric_definitions SET name='unauthorized'")
        unscoped = factory.connect()
        try:
            assert unscoped.execute("SELECT count(*) FROM reconforge.metric_snapshots").fetchone()[0] == 0
        finally:
            unscoped.close()

        with pytest.raises(DBAPIError, match="metrics downgrade refused: snapshots are retained"):
            command.downgrade(config, PREVIOUS)
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == CURRENT
        assert admin.execute("SELECT count(*) FROM reconforge.metric_snapshots").fetchone()[0] == 8
        command.upgrade(config, CURRENT)
        with boundary.transaction("metrics_a") as connection:
            assert MetricsApplicationService(PostgresMetricsRepository(connection, "metrics_a")).dashboard() == first

        # FORCE RLS also constrains a table owner. A migration role must never
        # mistake invisible snapshots for an empty table and drop their data.
        for table in ("metric_definitions", "metric_snapshots"):
            admin.execute(psycopg.sql.SQL("ALTER TABLE reconforge.{} OWNER TO {}").format(
                psycopg.sql.Identifier(table), role,
            ))
        admin.execute(psycopg.sql.SQL("ALTER TABLE alembic_version OWNER TO {}").format(role))
        app_url = URL.create(
            "postgresql+psycopg", username=parameters["user"], password=parameters.get("password"),
            host=parameters.get("host"), port=int(parameters.get("port", "5432")), database=parameters["dbname"],
        )
        with monkeypatch.context() as patch:
            patch.setenv("RECONFORGE_POSTGRES_DSN", app_url.render_as_string(hide_password=False))
            with pytest.raises(DBAPIError, match="row-level security"):
                command.downgrade(config, PREVIOUS)
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == CURRENT
        assert admin.execute("SELECT count(*) FROM reconforge.metric_snapshots").fetchone()[0] == 8


def test_live_metrics_downgrade_preserves_custom_definition(isolated_postgres_migration_dsn: str) -> None:
    import psycopg
    from sqlalchemy.exc import DBAPIError

    from alembic import command
    from reconforge.infrastructure.postgres_metrics import install_postgres_metrics_schema

    config = _migration_config()
    command.upgrade(config, PREVIOUS)
    with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
        # Earlier deployments could bootstrap metrics manually. Their reviewed
        # definitions must survive adoption by the migration chain unchanged.
        install_postgres_metrics_schema(admin)
        admin.execute("UPDATE reconforge.metric_definitions SET name='Reviewed custom label' WHERE metric_key='match_rate'")
        command.upgrade(config, CURRENT)
        assert admin.execute("SELECT name FROM reconforge.metric_definitions WHERE metric_key='match_rate'").fetchone()[0] == "Reviewed custom label"
        with pytest.raises(DBAPIError, match="metrics downgrade refused: custom definitions are retained"):
            command.downgrade(config, PREVIOUS)
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == CURRENT
        assert admin.execute("SELECT name FROM reconforge.metric_definitions WHERE metric_key='match_rate'").fetchone()[0] == "Reviewed custom label"
