from __future__ import annotations

import ast
import os
from collections.abc import Generator
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_postgres_migration_dsn(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    psycopg = pytest.importorskip("psycopg")
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN") or os.environ.get("RECONFORGE_POSTGRES_DSN", "")
    if not admin_dsn:
        pytest.skip("requires a disposable PostgreSQL administration service")
    database = "reconforge_migration_" + uuid4().hex[:20]
    parameters = psycopg.conninfo.conninfo_to_dict(admin_dsn)
    parameters["dbname"] = database
    target_dsn = psycopg.conninfo.make_conninfo(**parameters)
    target_url = (
        f"postgresql://{quote(parameters['user'], safe='')}:{quote(parameters.get('password', ''), safe='')}"
        f"@{parameters['host']}:{parameters.get('port', '5432')}/{quote(database, safe='')}"
    )
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(database)))
    monkeypatch.setenv("RECONFORGE_POSTGRES_DSN", target_url)
    try:
        yield target_dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                (database,),
            )
            admin.execute(psycopg.sql.SQL("DROP DATABASE {}").format(psycopg.sql.Identifier(database)))


def test_postgres_schema_migrations_use_sqlalchemy_text_for_plpgsql_format_tokens() -> None:
    for revision in sorted((ROOT / "alembic" / "versions").glob("*.py")):
        tree = ast.parse(revision.read_text(encoding="utf-8"), filename=str(revision))
        revision_ids = [
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "revision" for target in node.targets)
        ]
        assert len(revision_ids) == 1 and len(revision_ids[0]) <= 32, f"{revision.name} exceeds Alembic VARCHAR(32)"
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        assert not any(
            isinstance(call.func, ast.Attribute) and call.func.attr == "exec_driver_sql" for call in calls
        ), f"{revision.name} bypasses SQLAlchemy text escaping for migration SQL"


def test_postgres_alembic_assets_are_declared_for_sdist_and_wheel() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "include alembic.ini" in manifest
    assert "include reconforge_migration_sql.py" in manifest
    assert "include alembic/env.py" in manifest
    assert "include alembic/script.py.mako" in manifest
    assert "recursive-include alembic/versions *.py" in manifest
    assert '"." = ["alembic.ini"]' in project
    assert 'py-modules = ["reconforge_migration_sql"]' in project
    assert '"alembic" = ["alembic/env.py", "alembic/script.py.mako"]' in project
    assert '"alembic/versions" = ["alembic/versions/*.py"]' in project


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
    evidence_revision = (ROOT / "alembic" / "versions" / "0008_postgres_evidence_registry.py").read_text(
        encoding="utf-8"
    )
    reconciliation_revision = (ROOT / "alembic" / "versions" / "0009_postgres_reconciliation_results.py").read_text(
        encoding="utf-8"
    )
    execution_revision = (ROOT / "alembic" / "versions" / "0010_postgres_reconciliation_execution.py").read_text(
        encoding="utf-8"
    )
    checkpoint_revision = (ROOT / "alembic" / "versions" / "0011_postgres_reconciliation_checkpoints.py").read_text(
        encoding="utf-8"
    )
    jobs_revision = (ROOT / "alembic" / "versions" / "0012_postgres_durable_jobs.py").read_text(encoding="utf-8")
    domain_revision = (ROOT / "alembic" / "versions" / "0013_postgres_domain_uow.py").read_text(encoding="utf-8")
    operations_revision = (ROOT / "alembic" / "versions" / "0014_postgres_operations.py").read_text(encoding="utf-8")
    idempotency_revision = (ROOT / "alembic" / "versions" / "0015_postgres_idempotency.py").read_text(encoding="utf-8")
    journal_revision = (ROOT / "alembic" / "versions" / "0016_postgres_journals.py").read_text(encoding="utf-8")
    controls_revision = (ROOT / "alembic" / "versions" / "0017_postgres_control_testing.py").read_text(encoding="utf-8")
    intercompany_revision = (ROOT / "alembic" / "versions" / "0018_postgres_intercompany.py").read_text(
        encoding="utf-8"
    )
    finance_core_revision = (ROOT / "alembic" / "versions" / "0019_postgres_finance_core.py").read_text(
        encoding="utf-8"
    )
    master_data_application_revision = (
        ROOT / "alembic" / "versions" / "0020_postgres_master_data_application.py"
    ).read_text(encoding="utf-8")
    payables_revision = (ROOT / "alembic" / "versions" / "0021_postgres_payables.py").read_text(encoding="utf-8")
    receivables_revision = (ROOT / "alembic" / "versions" / "0022_postgres_receivables.py").read_text(encoding="utf-8")
    matching_application_revision = (ROOT / "alembic" / "versions" / "0023_postgres_matching_application.py").read_text(
        encoding="utf-8"
    )
    inventory_core_revision = (ROOT / "alembic" / "versions" / "0024_postgres_inventory_core.py").read_text(
        encoding="utf-8"
    )
    inventory_valuation_revision = (ROOT / "alembic" / "versions" / "0025_postgres_inventory_valuation.py").read_text(
        encoding="utf-8"
    )
    inventory_valuation_reversal_revision = (
        ROOT / "alembic" / "versions" / "0026_postgres_inventory_valuation_reversal.py"
    ).read_text(encoding="utf-8")
    inventory_planning_revision = (ROOT / "alembic" / "versions" / "0027_postgres_inventory_planning.py").read_text(
        encoding="utf-8"
    )
    accounts_revision = (ROOT / "alembic" / "versions" / "0028_postgres_accounts.py").read_text(encoding="utf-8")
    approvals_revision = (ROOT / "alembic" / "versions" / "0029_postgres_approvals.py").read_text(encoding="utf-8")
    close_application_revision = (ROOT / "alembic" / "versions" / "0030_postgres_close_application.py").read_text(
        encoding="utf-8"
    )
    evidence_application_revision = (ROOT / "alembic" / "versions" / "0031_postgres_evidence_application.py").read_text(
        encoding="utf-8"
    )
    exceptions_revision = (ROOT / "alembic" / "versions" / "0032_postgres_exceptions.py").read_text(encoding="utf-8")
    outbox_application_revision = (ROOT / "alembic" / "versions" / "0033_postgres_outbox_application.py").read_text(
        encoding="utf-8"
    )
    federation_revision = (ROOT / "alembic" / "versions" / "0034_postgres_federation.py").read_text(encoding="utf-8")
    scim_revision = (ROOT / "alembic" / "versions" / "0035_postgres_scim.py").read_text(encoding="utf-8")
    scim_auth_revision = (ROOT / "alembic" / "versions" / "0036_postgres_scim_auth.py").read_text(encoding="utf-8")
    service_account_revision = (ROOT / "alembic" / "versions" / "0037_postgres_service_accounts.py").read_text(
        encoding="utf-8"
    )
    privileged_session_revision = (
        ROOT / "alembic" / "versions" / "0038_postgres_privileged_sessions.py"
    ).read_text(encoding="utf-8")
    emergency_access_revision = (ROOT / "alembic" / "versions" / "0039_postgres_emergency_access.py").read_text(
        encoding="utf-8"
    )
    webauthn_revision = (ROOT / "alembic" / "versions" / "0040_postgres_webauthn_mfa.py").read_text(
        encoding="utf-8"
    )
    execution_scope_revision = (ROOT / "alembic" / "versions" / "0041_postgres_execution_scope.py").read_text(
        encoding="utf-8"
    )
    job_scope_revision = (ROOT / "alembic" / "versions" / "0042_postgres_job_scope.py").read_text(
        encoding="utf-8"
    )
    export_scope_revision = (ROOT / "alembic" / "versions" / "0043_postgres_export_scope.py").read_text(
        encoding="utf-8"
    )
    business_scope_revision = (
        ROOT / "alembic" / "versions" / "0044_postgres_business_scope.py"
    ).read_text(encoding="utf-8")
    workspace_attribution_revision = (
        ROOT / "alembic" / "versions" / "0045_postgres_workspace_attribution.py"
    ).read_text(encoding="utf-8")
    scope_authority_revision = (
        ROOT / "alembic" / "versions" / "0046_postgres_scope_authority.py"
    ).read_text(encoding="utf-8")
    scheduler_revision = (
        ROOT / "alembic" / "versions" / "0047_postgres_scheduler.py"
    ).read_text(encoding="utf-8")
    notification_revision = (
        ROOT / "alembic" / "versions" / "0048_postgres_notifications.py"
    ).read_text(encoding="utf-8")
    security_center_revision = (
        ROOT / "alembic" / "versions" / "0049_security_center_acl.py"
    ).read_text(encoding="utf-8")
    identity_admin_revision = (
        ROOT / "alembic" / "versions" / "0050_identity_administration_lifecycle.py"
    ).read_text(encoding="utf-8")
    access_policy_revision = (
        ROOT / "alembic" / "versions" / "0051_access_policy_lifecycle.py"
    ).read_text(encoding="utf-8")
    security_governance_revision = (
        ROOT / "alembic" / "versions" / "0052_security_governance.py"
    ).read_text(encoding="utf-8")
    audit_administration_revision = (
        ROOT / "alembic" / "versions" / "0053_audit_administration_acl.py"
    ).read_text(encoding="utf-8")

    assert "sqlalchemy.url =\n" in config
    assert "RECONFORGE_POSTGRES_DSN" in env
    assert "disable_existing_loggers=False" in env
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
    assert 'revision = "0015_postgres_idempotency"' in idempotency_revision
    assert 'down_revision = "0014_postgres_operations"' in idempotency_revision
    assert "POSTGRES_IDEMPOTENCY_SCHEMA_SQL" in idempotency_revision
    assert 'revision = "0016_postgres_journals"' in journal_revision
    assert 'down_revision = "0015_postgres_idempotency"' in journal_revision
    assert "POSTGRES_JOURNAL_SCHEMA_SQL" in journal_revision
    assert 'revision = "0017_postgres_control_testing"' in controls_revision
    assert 'down_revision = "0016_postgres_journals"' in controls_revision
    assert "POSTGRES_CONTROL_TESTING_SCHEMA_SQL" in controls_revision
    assert 'revision = "0018_postgres_intercompany"' in intercompany_revision
    assert 'down_revision = "0017_postgres_control_testing"' in intercompany_revision
    assert "POSTGRES_INTERCOMPANY_SCHEMA_SQL" in intercompany_revision
    assert 'revision = "0019_postgres_finance_core"' in finance_core_revision
    assert 'down_revision = "0018_postgres_intercompany"' in finance_core_revision
    assert "POSTGRES_FINANCE_CORE_SCHEMA_SQL" in finance_core_revision
    assert 'revision = "0020_postgres_master_data_app"' in master_data_application_revision
    assert 'down_revision = "0019_postgres_finance_core"' in master_data_application_revision
    assert "POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL" in master_data_application_revision
    assert 'revision = "0021_postgres_payables"' in payables_revision
    assert 'down_revision = "0020_postgres_master_data_app"' in payables_revision
    assert "POSTGRES_PAYABLES_SCHEMA_SQL" in payables_revision
    assert 'revision = "0022_postgres_receivables"' in receivables_revision
    assert 'down_revision = "0021_postgres_payables"' in receivables_revision
    assert "POSTGRES_RECEIVABLES_SCHEMA_SQL" in receivables_revision
    assert 'revision = "0023_postgres_matching_app"' in matching_application_revision
    assert 'down_revision = "0022_postgres_receivables"' in matching_application_revision
    assert "POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL" in matching_application_revision
    assert 'revision = "0024_postgres_inventory_core"' in inventory_core_revision
    assert 'down_revision = "0023_postgres_matching_app"' in inventory_core_revision
    assert "POSTGRES_INVENTORY_CORE_SCHEMA_SQL" in inventory_core_revision
    assert 'revision = "0025_postgres_inventory_value"' in inventory_valuation_revision
    assert 'down_revision = "0024_postgres_inventory_core"' in inventory_valuation_revision
    assert "POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL" in inventory_valuation_revision
    assert 'revision = "0026_postgres_inventory_reverse"' in inventory_valuation_reversal_revision
    assert 'down_revision = "0025_postgres_inventory_value"' in inventory_valuation_reversal_revision
    assert "POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL" in inventory_valuation_reversal_revision
    assert 'revision = "0027_postgres_inventory_planning"' in inventory_planning_revision
    assert 'down_revision = "0026_postgres_inventory_reverse"' in inventory_planning_revision
    assert "POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL" in inventory_planning_revision
    assert 'revision = "0028_postgres_accounts"' in accounts_revision
    assert 'down_revision = "0027_postgres_inventory_planning"' in accounts_revision
    assert "POSTGRES_ACCOUNTS_SCHEMA_SQL" in accounts_revision
    assert 'revision = "0029_postgres_approvals"' in approvals_revision
    assert 'down_revision = "0028_postgres_accounts"' in approvals_revision
    assert "POSTGRES_APPROVALS_SCHEMA_SQL" in approvals_revision
    assert 'revision = "0030_postgres_close_app"' in close_application_revision
    assert 'down_revision = "0029_postgres_approvals"' in close_application_revision
    assert "POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL" in close_application_revision
    assert 'revision = "0031_postgres_evidence_app"' in evidence_application_revision
    assert 'down_revision = "0030_postgres_close_app"' in evidence_application_revision
    assert "POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL" in evidence_application_revision
    assert 'revision = "0032_postgres_exceptions"' in exceptions_revision
    assert 'down_revision = "0031_postgres_evidence_app"' in exceptions_revision
    assert "POSTGRES_EXCEPTIONS_SCHEMA_SQL" in exceptions_revision
    assert 'revision = "0033_postgres_outbox_app"' in outbox_application_revision
    assert 'down_revision = "0032_postgres_exceptions"' in outbox_application_revision
    assert "POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL" in outbox_application_revision
    assert 'revision = "0034_postgres_federation"' in federation_revision
    assert 'down_revision = "0033_postgres_outbox_app"' in federation_revision
    assert "POSTGRES_FEDERATION_SCHEMA_SQL" in federation_revision
    assert 'revision = "0035_postgres_scim"' in scim_revision
    assert 'down_revision = "0034_postgres_federation"' in scim_revision
    assert "POSTGRES_SCIM_SCHEMA_SQL" in scim_revision
    assert 'revision = "0036_postgres_scim_auth"' in scim_auth_revision
    assert 'down_revision = "0035_postgres_scim"' in scim_auth_revision
    assert "POSTGRES_SCIM_AUTH_SCHEMA_SQL" in scim_auth_revision
    assert 'revision = "0037_postgres_service_accounts"' in service_account_revision
    assert 'down_revision = "0036_postgres_scim_auth"' in service_account_revision
    assert "POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL" in service_account_revision
    assert 'revision = "0038_postgres_step_up"' in privileged_session_revision
    assert 'down_revision = "0037_postgres_service_accounts"' in privileged_session_revision
    assert "POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL" in privileged_session_revision
    assert 'revision = "0039_postgres_emergency_access"' in emergency_access_revision
    assert 'down_revision = "0038_postgres_step_up"' in emergency_access_revision
    assert "POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL" in emergency_access_revision
    assert 'revision = "0040_postgres_webauthn_mfa"' in webauthn_revision
    assert 'revision = "0041_postgres_execution_scope"' in execution_scope_revision
    assert 'down_revision = "0040_postgres_webauthn_mfa"' in execution_scope_revision
    assert "POSTGRES_EXECUTION_SCOPE_SCHEMA_SQL" in execution_scope_revision
    assert 'revision = "0042_postgres_job_scope"' in job_scope_revision
    assert 'down_revision = "0041_postgres_execution_scope"' in job_scope_revision
    assert "POSTGRES_JOB_SCOPE_SCHEMA_SQL" in job_scope_revision
    assert 'revision = "0043_postgres_export_scope"' in export_scope_revision
    assert 'down_revision = "0042_postgres_job_scope"' in export_scope_revision
    assert "POSTGRES_EXPORT_SCOPE_SCHEMA_SQL" in export_scope_revision
    assert 'revision = "0044_postgres_business_scope"' in business_scope_revision
    assert 'down_revision = "0043_postgres_export_scope"' in business_scope_revision
    assert "POSTGRES_BUSINESS_SCOPE_SCHEMA_SQL" in business_scope_revision
    assert 'revision = "0045_postgres_workspace_scope"' in workspace_attribution_revision
    assert 'down_revision = "0044_postgres_business_scope"' in workspace_attribution_revision
    assert "POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL" in workspace_attribution_revision
    assert 'revision = "0046_postgres_scope_authority"' in scope_authority_revision
    assert 'down_revision = "0045_postgres_workspace_scope"' in scope_authority_revision
    assert "POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL" in scope_authority_revision
    assert 'revision = "0047_postgres_scheduler"' in scheduler_revision
    assert 'down_revision = "0046_postgres_scope_authority"' in scheduler_revision
    assert "POSTGRES_SCHEDULER_SCHEMA_SQL" in scheduler_revision
    assert "downgrade refuses non-empty scheduler evidence" in scheduler_revision
    assert 'revision = "0048_postgres_notifications"' in notification_revision
    assert 'down_revision = "0047_postgres_scheduler"' in notification_revision
    assert "POSTGRES_NOTIFICATION_SCHEMA_SQL" in notification_revision
    assert "downgrade refuses non-empty notification evidence" in notification_revision
    assert 'revision = "0049_security_center_acl"' in security_center_revision
    assert 'down_revision = "0048_postgres_notifications"' in security_center_revision
    assert "service_account_permissions_human_only" in security_center_revision
    assert 'revision = "0050_identity_admin_lifecycle"' in identity_admin_revision
    assert 'down_revision = "0049_security_center_acl"' in identity_admin_revision
    assert "governed identity lifecycle evidence would be lost" in identity_admin_revision
    assert 'revision = "0051_access_policy_lifecycle"' in access_policy_revision
    assert 'down_revision = "0050_identity_admin_lifecycle"' in access_policy_revision
    assert "refusing to discard governed access-policy lifecycle evidence" in access_policy_revision
    assert 'revision = "0052_security_governance"' in security_governance_revision
    assert 'down_revision = "0051_access_policy_lifecycle"' in security_governance_revision
    assert "POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL" in security_governance_revision
    assert "refusing to discard governed retention policy" in security_governance_revision
    assert 'revision = "0053_audit_administration_acl"' in audit_administration_revision
    assert 'down_revision = "0052_security_governance"' in audit_administration_revision
    assert "'audit.read','audit.verify'" in audit_administration_revision
    assert "NOT VALID" in audit_administration_revision
    assert 'down_revision = "0039_postgres_emergency_access"' in webauthn_revision
    assert "POSTGRES_WEBAUTHN_SCHEMA_SQL" in webauthn_revision
    assert "password" not in config.lower()


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_POSTGRES_DSN"), reason="requires a live PostgreSQL migration service"
)
def test_alembic_upgrade_command_is_available_when_server_extra_is_installed(
    isolated_postgres_migration_dsn: str,
) -> None:
    alembic = pytest.importorskip("alembic")
    psycopg = pytest.importorskip("psycopg")
    from alembic.config import Config

    from alembic import command
    from reconforge.application.operations import MigrationStatus
    from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
    from reconforge.infrastructure.postgres_operations import PostgresMigrationStatusProvider

    assert alembic is not None and isolated_postgres_migration_dsn
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    command.current(config)
    command.downgrade(config, "0051_access_policy_lifecycle")
    with psycopg.connect(os.environ["RECONFORGE_POSTGRES_DSN"]) as connection:
        assert connection.execute("SELECT to_regclass('reconforge.retention_policies')").fetchone()[0] is None
        assert connection.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='reconforge' AND table_name='evidence_registry' "
            "AND column_name='retention_version'"
        ).fetchone() is None
    command.upgrade(config, "head")
    command.downgrade(config, "0011_postgres_recon_ckpts")
    with psycopg.connect(os.environ["RECONFORGE_POSTGRES_DSN"]) as connection:
        assert connection.execute("SELECT to_regclass('reconforge.journal_entries')").fetchone()[0] is None
        assert connection.execute("SELECT to_regclass('reconforge.intercompany_cases')").fetchone()[0] is None
        assert connection.execute("SELECT to_regclass('reconforge.durable_jobs')").fetchone()[0] is None
        assert (
            connection.execute("SELECT to_regclass('reconforge.reconciliation_execution_checkpoints')").fetchone()[0]
            == "reconforge.reconciliation_execution_checkpoints"
        )
    command.upgrade(config, "head")
    with psycopg.connect(os.environ["RECONFORGE_POSTGRES_DSN"]) as connection:
        assert (
            connection.execute("SELECT to_regclass('reconforge.durable_job_partition_effects')").fetchone()[0]
            == "reconforge.durable_job_partition_effects"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.domain_audit_events')").fetchone()[0]
            == "reconforge.domain_audit_events"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.ops_job_history')").fetchone()[0]
            == "reconforge.ops_job_history"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.idempotency_records')").fetchone()[0]
            == "reconforge.idempotency_records"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.journal_entries')").fetchone()[0]
            == "reconforge.journal_entries"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.control_test_results')").fetchone()[0]
            == "reconforge.control_test_results"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.intercompany_cases')").fetchone()[0]
            == "reconforge.intercompany_cases"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.finance_entries')").fetchone()[0]
            == "reconforge.finance_entries"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.master_data_workspace_organizations')").fetchone()[0]
            == "reconforge.master_data_workspace_organizations"
        )
        assert connection.execute("SELECT to_regclass('reconforge.ap_suppliers')").fetchone()[0] == (
            "reconforge.ap_suppliers"
        )
        assert connection.execute("SELECT to_regclass('reconforge.ar_customers')").fetchone()[0] == (
            "reconforge.ar_customers"
        )
        assert connection.execute("SELECT to_regclass('reconforge.matching_run_workspaces')").fetchone()[0] == (
            "reconforge.matching_run_workspaces"
        )
        assert connection.execute("SELECT to_regclass('reconforge.inventory_movements')").fetchone()[0] == (
            "reconforge.inventory_movements"
        )
        assert connection.execute("SELECT to_regclass('reconforge.inventory_cost_layers')").fetchone()[0] == (
            "reconforge.inventory_cost_layers"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.inventory_valuation_reversals')").fetchone()[0]
            == "reconforge.inventory_valuation_reversals"
        )
        assert connection.execute("SELECT to_regclass('reconforge.inventory_count_sessions')").fetchone()[0] == (
            "reconforge.inventory_count_sessions"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.account_reconciliation_records')").fetchone()[0]
            == "reconforge.account_reconciliation_records"
        )
        assert connection.execute("SELECT to_regclass('reconforge.approval_requests')").fetchone()[0] == (
            "reconforge.approval_requests"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.close_application_periods')").fetchone()[0]
            == "reconforge.close_application_periods"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.evidence_application_registry')").fetchone()[0]
            == "reconforge.evidence_application_registry"
        )
        assert (
            connection.execute("SELECT to_regclass('reconforge.exception_queue_records')").fetchone()[0]
            == "reconforge.exception_queue_records"
        )
        assert (
            connection.execute("SELECT dead_lettered_at FROM reconforge.outbox_events LIMIT 0").description is not None
        )
        assert connection.execute("SELECT to_regclass('reconforge.scim_users')").fetchone()[0] == (
            "reconforge.scim_users"
        )
        assert connection.execute("SELECT to_regclass('reconforge.scim_group_members')").fetchone()[0] == (
            "reconforge.scim_group_members"
        )
        assert connection.execute("SELECT to_regclass('reconforge.scim_credentials')").fetchone()[0] == (
            "reconforge.scim_credentials"
        )
        assert connection.execute("SELECT to_regclass('reconforge.service_accounts')").fetchone()[0] == (
            "reconforge.service_accounts"
        )
        assert connection.execute("SELECT to_regclass('reconforge.identity_webauthn_credentials')").fetchone()[0] == (
            "reconforge.identity_webauthn_credentials"
        )
        assert connection.execute("SELECT to_regclass('reconforge.schedules')").fetchone()[0] == (
            "reconforge.schedules"
        )
        assert connection.execute("SELECT to_regclass('reconforge.schedule_dispatches')").fetchone()[0] == (
            "reconforge.schedule_dispatches"
        )
        assert connection.execute("SELECT to_regclass('reconforge.notification_routes')").fetchone()[0] == (
            "reconforge.notification_routes"
        )
        assert connection.execute(
            "SELECT to_regclass('reconforge.notification_delivery_events')"
        ).fetchone()[0] == "reconforge.notification_delivery_events"
        assert connection.execute("SELECT to_regclass('reconforge.retention_policies')").fetchone()[0] == (
            "reconforge.retention_policies"
        )
        assert connection.execute(
            "SELECT to_regclass('reconforge.evidence_retention_assignments')"
        ).fetchone()[0] == "reconforge.evidence_retention_assignments"
        assert connection.execute("SELECT to_regclass('reconforge.policy_delegations')").fetchone()[0] == (
            "reconforge.policy_delegations"
        )
        assert connection.execute("SELECT to_regclass('reconforge.connector_writeback_intents')").fetchone()[0] == (
            "reconforge.connector_writeback_intents"
        )
        assert connection.execute("SELECT to_regclass('reconforge.outbox_consumer_receipts')").fetchone()[0] == (
            "reconforge.outbox_consumer_receipts"
        )
    provider = PostgresMigrationStatusProvider(
        PostgresConnectionFactory(PostgresSettings(dsn=os.environ["RECONFORGE_POSTGRES_DSN"], require_tls=False))
    )
    assert provider("migration-test") == MigrationStatus(
        "0071_pg_close_ownchg_links", "0071_pg_close_ownchg_links", ()
    )
