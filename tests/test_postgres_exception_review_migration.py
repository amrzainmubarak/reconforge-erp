"""Acceptance for the registered PostgreSQL exception-review migration."""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic/versions/0104_postgres_exception_review_api.py"
PREVIOUS = "0103_pg_outbox_fencing"
CURRENT = "0104_pg_exception_review_api"
pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="requires owned live PostgreSQL fixture",
)


def migrate(
    dsn: str,
    action: str,
    target: str,
    *,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", action, target],
        cwd=ROOT,
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn, **(extra_environment or {})},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def prior_database() -> Iterator[str]:
    import psycopg
    from psycopg import sql

    database = "reconforge_exception_review_migration_" + uuid4().hex[:12]
    control_dsn = psycopg.conninfo.make_conninfo(
        os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"],
        dbname="postgres",
        connect_timeout=5,
    )
    admin_dsn = urlunsplit(
        urlsplit(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])._replace(path="/" + database)
    )
    with psycopg.connect(control_dsn, autocommit=True) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        result = migrate(admin_dsn, "upgrade", PREVIOUS)
        assert result.returncode == 0, result.stderr
        yield admin_dsn
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None


def _current_revision(connection: object) -> str:
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()  # type: ignore[attr-defined]
    assert row is not None
    return str(row[0])


def _insert_legacy_exception(connection: object) -> None:
    execute = connection.execute  # type: ignore[attr-defined]
    execute("INSERT INTO reconforge.tenants(id,name) VALUES ('exception-existing','Exception existing')")
    execute(
        "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES "
        "('exception-existing','workspace-existing','existing')"
    )
    execute(
        "INSERT INTO reconforge.identity_roles(tenant_id,id,name) VALUES "
        "('exception-existing','role-reviewer-existing','reviewer')"
    )
    from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository

    PostgresIdentityRepository(connection).create_user(  # type: ignore[arg-type]
        tenant_id="exception-existing",
        user_id="maker-existing",
        username="maker-renamed",
        password="Synthetic-password-123",
        role_name="reviewer",
    )
    execute(
        """INSERT INTO reconforge.exception_queue_records(
        tenant_id,id,workspace_id,source_type,source_id,description,created_by,last_actor)
        VALUES ('exception-existing','exception-existing','workspace-existing','control','source-existing',
                'Retained existing exception','maker-existing','maker-existing')"""
    )
    execute(
        """INSERT INTO reconforge.exception_queue_records(
        tenant_id,id,workspace_id,source_type,source_id,description,created_by,last_actor)
        VALUES ('exception-existing','exception-label-only','workspace-existing','control','source-label-only',
                'Retained label-only exception','maker-renamed','maker-renamed')"""
    )
    execute(
        """INSERT INTO reconforge.exception_queue_history(
        tenant_id,id,exception_id,action,from_status,to_status,from_owner,to_owner,actor_label)
        VALUES ('exception-existing','history-existing','exception-existing','exception_saved','','Open','','',
                'maker-existing')"""
    )


def test_exception_review_migration_is_frozen_and_has_no_runtime_schema_dependency() -> None:
    spec = importlib.util.spec_from_file_location("exception_review_frozen_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == CURRENT
    assert module.down_revision == PREVIOUS
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    assignments = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    for name in ("UPGRADE_SQL", "DOWNGRADE_SQL"):
        value = assignments.get(name)
        assert isinstance(value, ast.Constant)
        assert isinstance(value.value, str)
    assert sha256(module.UPGRADE_SQL.encode("utf-8")).hexdigest() == (
        "3f357d7b1564b729e631975301cb560ba04108d19576bff8782bad4b6bafbe98"
    )
    assert sha256(module.DOWNGRADE_SQL.encode("utf-8")).hexdigest() == (
        "81ac243147769e922fb26e6a2b43cb9844add95b551c42a06015964f8e078325"
    )
    source = MIGRATION.read_text(encoding="utf-8")
    assert "postgres_exceptions" not in source
    assert "op.execute(UPGRADE_SQL)" in source
    seed_trigger = source.index("CREATE TRIGGER exception_review_permission_tenant_seed")
    assert seed_trigger < source.index(
        "INSERT INTO reconforge.identity_permissions", seed_trigger
    )


def test_registered_exception_review_upgrade_retains_legacy_rows_and_refuses_lossy_downgrade(
    prior_database: str,
) -> None:
    import psycopg

    with psycopg.connect(prior_database, autocommit=True) as administrator:
        _insert_legacy_exception(administrator)
    result = migrate(
        prior_database,
        "upgrade",
        CURRENT,
        extra_environment={
            "PGOPTIONS": "-c app.organization_id=organization-from-guc -c app.legal_entity_id=entity-from-guc"
        },
    )
    assert result.returncode == 0, result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        assert _current_revision(administrator) == CURRENT
        columns = tuple(
            row[0]
            for row in administrator.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='reconforge' AND table_name='exception_queue_history' ORDER BY column_name"
            ).fetchall()
        )
        assert {"actor_id", "reason"}.issubset(columns)
        record = administrator.execute(
            "SELECT organization_id,legal_entity_id,created_by_actor_id FROM reconforge.exception_queue_records "
            "WHERE tenant_id='exception-existing' AND id='exception-existing'"
        ).fetchone()
        label_only = administrator.execute(
            "SELECT organization_id,legal_entity_id,created_by_actor_id FROM reconforge.exception_queue_records "
            "WHERE tenant_id='exception-existing' AND id='exception-label-only'"
        ).fetchone()
        history = administrator.execute(
            "SELECT actor_id,reason FROM reconforge.exception_queue_history "
            "WHERE tenant_id='exception-existing'"
        ).fetchone()
        assert record == (None, None, "maker-existing")
        assert label_only == (None, None, None)
        assert history == ("", "")
        permissions = tuple(
            row[0]
            for row in administrator.execute(
                "SELECT name FROM reconforge.identity_permissions WHERE tenant_id='exception-existing' "
                "AND name LIKE 'exceptions.%' ORDER BY name"
            ).fetchall()
        )
        assignments = tuple(
            row[0]
            for row in administrator.execute(
                "SELECT permission_name FROM reconforge.identity_role_permissions "
                "WHERE tenant_id='exception-existing' AND role_id='role-reviewer-existing' "
                "ORDER BY permission_name"
            ).fetchall()
        )
        assert permissions == ("exceptions.manage", "exceptions.read")
        assert assignments == ("exceptions.manage", "exceptions.read")
        administrator.execute("INSERT INTO reconforge.tenants(id,name) VALUES('exception-future','future')")
        administrator.execute(
            "INSERT INTO reconforge.identity_roles(tenant_id,id,name) VALUES "
            "('exception-future','role-reviewer-future','reviewer')"
        )
        future_assignments = tuple(
            row[0]
            for row in administrator.execute(
                "SELECT permission_name FROM reconforge.identity_role_permissions "
                "WHERE tenant_id='exception-future' AND role_id='role-reviewer-future' "
                "ORDER BY permission_name"
            ).fetchall()
        )
        assert future_assignments == ("exceptions.manage", "exceptions.read")
        rls = administrator.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_catalog.pg_class "
            "WHERE oid='reconforge.exception_queue_records'::regclass"
        ).fetchone()
        assert rls == (True, True)
        policy = administrator.execute(
            "SELECT qual FROM pg_policies WHERE schemaname='reconforge' "
            "AND tablename='exception_queue_records' AND policyname='tenant_scope'"
        ).fetchone()
        assert policy is not None and "app.legal_entity_id" in str(policy[0])

    result = migrate(prior_database, "downgrade", PREVIOUS)
    assert result.returncode != 0
    assert "scoped exception review evidence prevents downgrade" in result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        assert _current_revision(administrator) == CURRENT


def test_exception_review_migration_role_admission_leaves_no_partial_mutation(prior_database: str) -> None:
    """Both directions reject a non-bypass role before scoped DDL or data access."""

    import psycopg
    from psycopg import sql

    role_name = "exception_review_migration_" + uuid4().hex[:12]
    role_password = "Synthetic-password-123"
    control_dsn = psycopg.conninfo.make_conninfo(
        os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"],
        dbname="postgres",
        connect_timeout=5,
    )
    parsed_prior_dsn = urlsplit(prior_database)
    low_dsn = urlunsplit(
        parsed_prior_dsn._replace(
            netloc=f"{role_name}:{role_password}@{parsed_prior_dsn.hostname}:{parsed_prior_dsn.port}"
        )
    )
    try:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS").format(
                    sql.Identifier(role_name),
                    sql.Literal(role_password),
                )
            )
        with psycopg.connect(prior_database, autocommit=True) as administrator:
            administrator.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(urlsplit(prior_database).path.lstrip("/")), sql.Identifier(role_name)
            ))
            administrator.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(role_name)))
            administrator.execute(sql.SQL("GRANT SELECT ON alembic_version TO {}").format(sql.Identifier(role_name)))

        rejected_upgrade = migrate(low_dsn, "upgrade", CURRENT)
        assert rejected_upgrade.returncode != 0
        assert "requires a role that bypasses forced row security" in (
            rejected_upgrade.stdout + rejected_upgrade.stderr
        )
        with psycopg.connect(prior_database, autocommit=True) as administrator:
            assert _current_revision(administrator) == PREVIOUS
            assert administrator.execute(
                "SELECT to_regclass('reconforge.exception_review_evidence')"
            ).fetchone() == (None,)
            assert administrator.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema='reconforge' "
                "AND table_name='exception_queue_records' AND column_name='created_by_actor_id'"
            ).fetchone() == (0,)

        accepted_upgrade = migrate(prior_database, "upgrade", CURRENT)
        assert accepted_upgrade.returncode == 0, accepted_upgrade.stderr
        rejected_downgrade = migrate(low_dsn, "downgrade", PREVIOUS)
        assert rejected_downgrade.returncode != 0
        assert "requires a role that bypasses forced row security" in (
            rejected_downgrade.stdout + rejected_downgrade.stderr
        )
        with psycopg.connect(prior_database, autocommit=True) as administrator:
            assert _current_revision(administrator) == CURRENT
            assert administrator.execute(
                "SELECT to_regclass('reconforge.exception_review_evidence')"
            ).fetchone() == ("reconforge.exception_review_evidence",)
    finally:
        with psycopg.connect(prior_database, autocommit=True) as administrator:
            administrator.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name)))


def test_registered_exception_review_empty_upgrade_downgrade_and_reupgrade_are_reversible(
    prior_database: str,
) -> None:
    result = migrate(prior_database, "upgrade", CURRENT)
    assert result.returncode == 0, result.stderr
    result = migrate(prior_database, "downgrade", PREVIOUS)
    assert result.returncode == 0, result.stderr
    result = migrate(prior_database, "upgrade", CURRENT)
    assert result.returncode == 0, result.stderr
