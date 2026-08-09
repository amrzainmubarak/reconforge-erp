from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.professional_invoice_payment_control import (
    run_professional_invoice_payment_control_files,
    verify_professional_invoice_payment_report,
    write_professional_invoice_payment_report,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_professional_invoice_payment import (
    POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL,
    PostgresProfessionalInvoicePaymentRepository,
)

ROOT = Path(__file__).resolve().parents[1]
INVOICES = ROOT / "examples/professional_invoice_payment/invoices.json"
PAYMENTS = ROOT / "examples/professional_invoice_payment/payments.json"


def _report(tmp_path: Path) -> dict[str, object]:
    report_path = tmp_path / "professional-report.json"
    run = run_professional_invoice_payment_control_files(INVOICES, PAYMENTS, currency="USD", tolerance="0.01")
    write_professional_invoice_payment_report(run, report_path)
    return verify_professional_invoice_payment_report(report_path)


def test_postgres_professional_invoice_payment_schema_is_rls_immutable_and_bounded() -> None:
    assert "JSONB NOT NULL" in POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL
    assert "tenant_id = current_setting('app.tenant_id', true)" in POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL
    assert "workspace_id = current_setting('app.workspace_id', true)" in POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL
    assert "professional invoice/payment evidence is immutable" in POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL
    assert "professional invoice/payment evidence cannot be deleted" in POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL
    assert "secret" not in POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL.casefold()


def test_postgres_professional_invoice_payment_migration_is_versioned_and_non_destructive() -> None:
    migration = (ROOT / "alembic/versions/0081_postgres_professional_invoice_payment.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0081_pg_prof_invoice"' in migration
    assert 'down_revision = "0080_pg_retail_settlement"' in migration
    assert "POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL" in migration
    assert "refusing to discard professional invoice/payment evidence" in migration
    assert "DROP TABLE IF EXISTS reconforge.professional_invoice_payment_runs" in migration


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_professional_invoice_payment_is_scoped_idempotent_and_append_only(tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")

    tenant_id = "pipg_" + uuid4().hex[:10]
    workspace_id = "professional-workspace"
    other_tenant = "pipg_other_" + uuid4().hex[:8]
    report = _report(tmp_path)
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))

    admin_connection = None
    connection = None
    try:
        admin_connection = admin_factory.connect()
        with admin_connection.transaction():
            install_postgres_rls_schema(admin_connection)
            admin_connection.execute(POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL)
            admin_connection.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin_connection.execute(
                "GRANT SELECT, INSERT ON reconforge.professional_invoice_payment_runs TO " f"{app_user}"
            )
            admin_connection.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s), (%s, %s)",
                (tenant_id, tenant_id, other_tenant, other_tenant),
            )
        connection = app_factory.connect()
        repository = PostgresProfessionalInvoicePaymentRepository(connection)
        stored = repository.put_payload(
            report,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_label="server-admin",
        )
        assert repository.put_payload(
            report,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_label="server-admin",
        ) == stored
        assert repository.get(
            decision_digest=str(report["decision_digest"]),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        ) == stored
        assert repository.list(tenant_id=tenant_id, workspace_id=workspace_id) == (stored,)
        assert repository.get(
            decision_digest=str(report["decision_digest"]),
            tenant_id=other_tenant,
            workspace_id=workspace_id,
        ) is None
        with pytest.raises(psycopg.Error, match="immutable"), admin_connection.transaction():
            admin_connection.execute(
                "UPDATE reconforge.professional_invoice_payment_runs SET prepared_by='tampered' "
                "WHERE tenant_id=%s AND workspace_id=%s",
                (tenant_id, workspace_id),
            )
    finally:
        if connection is not None:
            connection.close()
        if admin_connection is not None:
            admin_connection.close()
