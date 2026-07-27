from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_alembic_contract_has_no_repository_credentials() -> None:
    config = (ROOT / "alembic.ini").read_text(encoding="utf-8")
    env = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    revision = (ROOT / "alembic" / "versions" / "0001_postgres_tenant_boundary.py").read_text(encoding="utf-8")
    master_revision = (ROOT / "alembic" / "versions" / "0002_postgres_master_data.py").read_text(encoding="utf-8")
    ledger_revision = (ROOT / "alembic" / "versions" / "0003_postgres_ledger.py").read_text(encoding="utf-8")
    identity_revision = (ROOT / "alembic" / "versions" / "0004_postgres_identity.py").read_text(encoding="utf-8")
    periods_revision = (ROOT / "alembic" / "versions" / "0005_postgres_fiscal_periods.py").read_text(encoding="utf-8")
    close_revision = (ROOT / "alembic" / "versions" / "0006_postgres_close.py").read_text(encoding="utf-8")
    outbox_revision = (ROOT / "alembic" / "versions" / "0007_postgres_outbox_delivery.py").read_text(encoding="utf-8")
    evidence_revision = (ROOT / "alembic" / "versions" / "0008_postgres_evidence_registry.py").read_text(encoding="utf-8")
    reconciliation_revision = (ROOT / "alembic" / "versions" / "0009_postgres_reconciliation_results.py").read_text(encoding="utf-8")
    execution_revision = (ROOT / "alembic" / "versions" / "0010_postgres_reconciliation_execution.py").read_text(encoding="utf-8")
    checkpoint_revision = (ROOT / "alembic" / "versions" / "0011_postgres_reconciliation_checkpoints.py").read_text(encoding="utf-8")
    jobs_revision = (ROOT / "alembic" / "versions" / "0012_postgres_durable_jobs.py").read_text(encoding="utf-8")
    domain_revision = (ROOT / "alembic" / "versions" / "0013_postgres_domain_uow.py").read_text(encoding="utf-8")
    operations_revision = (ROOT / "alembic" / "versions" / "0014_postgres_operations.py").read_text(encoding="utf-8")

    assert "sqlalchemy.url =\n" in config
    assert "RECONFORGE_POSTGRES_DSN" in env
    assert "postgresql+psycopg://" in env
    assert "POSTGRES_RLS_SCHEMA_SQL" in revision
    assert 'revision = "0002_postgres_master_data"' in master_revision
    assert 'down_revision = "0001_postgres_tenant_boundary"' in master_revision
    assert "POSTGRES_MASTER_DATA_SCHEMA_SQL" in master_revision
    assert 'revision = "0003_postgres_ledger"' in ledger_revision
    assert 'down_revision = "0002_postgres_master_data"' in ledger_revision
    assert "POSTGRES_LEDGER_SCHEMA_SQL" in ledger_revision
    assert 'revision = "0004_postgres_identity"' in identity_revision
    assert 'down_revision = "0003_postgres_ledger"' in identity_revision
    assert "POSTGRES_IDENTITY_SCHEMA_SQL" in identity_revision
    assert 'revision = "0005_postgres_fiscal_periods"' in periods_revision
    assert 'down_revision = "0004_postgres_identity"' in periods_revision
    assert "POSTGRES_FISCAL_PERIOD_SCHEMA_SQL" in periods_revision
    assert 'revision = "0006_postgres_close"' in close_revision
    assert 'down_revision = "0005_postgres_fiscal_periods"' in close_revision
    assert "POSTGRES_CLOSE_SCHEMA_SQL" in close_revision
    assert 'revision = "0007_postgres_outbox_delivery"' in outbox_revision
    assert 'down_revision = "0006_postgres_close"' in outbox_revision
    assert "claimed_by" in outbox_revision
    assert 'revision = "0008_postgres_evidence_registry"' in evidence_revision
    assert 'down_revision = "0007_postgres_outbox_delivery"' in evidence_revision
    assert "POSTGRES_EVIDENCE_SCHEMA_SQL" in evidence_revision
    assert 'revision = "0009_postgres_recon_results"' in reconciliation_revision
    assert 'down_revision = "0008_postgres_evidence_registry"' in reconciliation_revision
    assert "POSTGRES_RECONCILIATION_SCHEMA_SQL" in reconciliation_revision
    assert 'revision = "0010_postgres_recon_exec"' in execution_revision
    assert 'down_revision = "0009_postgres_recon_results"' in execution_revision
    assert "POSTGRES_RECONCILIATION_EXECUTION_SCHEMA_SQL" in execution_revision
    assert 'revision = "0011_postgres_recon_ckpts"' in checkpoint_revision
    assert 'down_revision = "0010_postgres_recon_exec"' in checkpoint_revision
    assert "POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL" in checkpoint_revision
    assert 'revision = "0012_postgres_jobs"' in jobs_revision
    assert 'down_revision = "0011_postgres_recon_ckpts"' in jobs_revision
    assert "POSTGRES_DURABLE_JOB_SCHEMA_SQL" in jobs_revision
    assert 'revision = "0013_postgres_domain_uow"' in domain_revision
    assert 'down_revision = "0012_postgres_jobs"' in domain_revision
    assert "POSTGRES_DOMAIN_SCHEMA_SQL" in domain_revision
    assert 'revision = "0014_postgres_operations"' in operations_revision
    assert 'down_revision = "0013_postgres_domain_uow"' in operations_revision
    assert "POSTGRES_OPERATIONS_SCHEMA_SQL" in operations_revision
    assert "password" not in config.lower()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_POSTGRES_DSN"), reason="requires a live PostgreSQL migration service")
def test_alembic_upgrade_command_is_available_when_server_extra_is_installed() -> None:
    alembic = pytest.importorskip("alembic")
    psycopg = pytest.importorskip("psycopg")
    from alembic.config import Config

    from alembic import command
    from reconforge.application.operations import MigrationStatus
    from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
    from reconforge.infrastructure.postgres_operations import PostgresMigrationStatusProvider

    assert alembic is not None
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    command.current(config)
    command.downgrade(config, "0011_postgres_recon_ckpts")
    with psycopg.connect(os.environ["RECONFORGE_POSTGRES_DSN"]) as connection:
        assert connection.execute(
            "SELECT to_regclass('reconforge.durable_jobs')"
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT to_regclass('reconforge.reconciliation_execution_checkpoints')"
        ).fetchone()[0] == "reconforge.reconciliation_execution_checkpoints"
    command.upgrade(config, "head")
    with psycopg.connect(os.environ["RECONFORGE_POSTGRES_DSN"]) as connection:
        assert connection.execute(
            "SELECT to_regclass('reconforge.durable_job_partition_effects')"
        ).fetchone()[0] == "reconforge.durable_job_partition_effects"
        assert connection.execute(
            "SELECT to_regclass('reconforge.domain_audit_events')"
        ).fetchone()[0] == "reconforge.domain_audit_events"
        assert connection.execute(
            "SELECT to_regclass('reconforge.ops_job_history')"
        ).fetchone()[0] == "reconforge.ops_job_history"
    provider = PostgresMigrationStatusProvider(
        PostgresConnectionFactory(
            PostgresSettings(dsn=os.environ["RECONFORGE_POSTGRES_DSN"], require_tls=False)
        )
    )
    assert provider("migration-test") == MigrationStatus(
        "0014_postgres_operations", "0014_postgres_operations", ()
    )
