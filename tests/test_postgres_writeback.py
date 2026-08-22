from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest

from reconforge.application.writeback import WritebackIntentApplicationService
from reconforge.connectors.erpnext_payment_writeback import (
    ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION,
    ErpNextPaymentEntryDraft,
    build_erpnext_payment_entry_payload,
)
from reconforge.connectors.writeback import (
    WritebackPolicy,
    WritebackStatus,
    acknowledge_writeback,
    approve_writeback,
    dispatch_writeback,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_writeback import (
    POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_AUDIT_SQL,
    POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL,
    POSTGRES_WRITEBACK_SCHEMA_SQL,
    PostgresWritebackIntentRepository,
    PostgresWritebackPersistenceError,
)
from tests.test_connector_writeback import NOW, POLICY, _intent


def test_postgres_writeback_schema_is_rls_append_only_and_secret_free() -> None:
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_WRITEBACK_SCHEMA_SQL
    assert "JSONB NOT NULL" in POSTGRES_WRITEBACK_SCHEMA_SQL
    assert "connector write-back intents are immutable" in POSTGRES_WRITEBACK_SCHEMA_SQL
    assert "connector write-back intents cannot be deleted" in POSTGRES_WRITEBACK_SCHEMA_SQL
    assert "tenant_id = current_setting('app.tenant_id', true)" in POSTGRES_WRITEBACK_SCHEMA_SQL
    assert "secret" not in POSTGRES_WRITEBACK_SCHEMA_SQL.casefold()
    assert "BEFORE INSERT OR UPDATE OR DELETE" in POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL
    assert "connector write-back predecessor is missing" in POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL
    assert "proposal identity is immutable" in POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL
    assert "requested_at" in POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL
    assert "existing connector write-back history violates" in POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_AUDIT_SQL
    assert "previous.version IS NULL" in POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_AUDIT_SQL


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_writeback_history_is_scoped_idempotent_and_append_only() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_id = "wbpg_" + uuid4().hex[:8]
    workspace_id = "workspace-wbpg"
    admin = admin_factory.connect()
    connection = None
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_WRITEBACK_SCHEMA_SQL)
            admin.execute(POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                "GRANT SELECT, INSERT ON reconforge.connector_writeback_intents TO "
                f"{app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)",
                (tenant_id, tenant_id),
            )
        connection = factory.connect()
        repository = PostgresWritebackIntentRepository(connection)
        service = WritebackIntentApplicationService(repository)
        proposed = _intent(
            intent_id="intent-" + uuid4().hex[:16],
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            idempotency_key="wbpg-" + uuid4().hex[:16],
        )
        assert service.put(proposed) == proposed
        assert service.put(proposed) == proposed
        approved = approve_writeback(
            proposed,
            policy=POLICY,
            actor_id="checker-1",
            approved_at=NOW,
            assurance="mfa",
            reason="independent synthetic review",
        )
        with pytest.raises(PostgresWritebackPersistenceError, match="writeback_proposal_identity_immutable"):
            service.put(approved.model_copy(update={"operation": "payment.update"}), expected_version=1)
        missing_operation = approved.model_dump(mode="json", exclude_none=False)
        missing_operation.pop("operation")
        with pytest.raises(psycopg.Error, match="fields are missing or invalid"), admin.transaction():
            admin.execute(
                """
                INSERT INTO reconforge.connector_writeback_intents(
                    tenant_id,intent_id,workspace_id,version,status,intent_digest,intent_json
                ) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    approved.tenant_id,
                    approved.intent_id,
                    approved.workspace_id,
                    2,
                    approved.status.value,
                    approved.digest,
                    json.dumps(missing_operation),
                ),
            )
        drifted = approved.model_copy(update={"payload_digest": "f" * 64})
        with pytest.raises(psycopg.Error, match="proposal identity is immutable"), admin.transaction():
            admin.execute(
                """
                INSERT INTO reconforge.connector_writeback_intents(
                    tenant_id,intent_id,workspace_id,version,status,intent_digest,intent_json
                ) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    drifted.tenant_id,
                    drifted.intent_id,
                    drifted.workspace_id,
                    2,
                    drifted.status.value,
                    drifted.digest,
                    json.dumps(drifted.model_dump(mode="json", exclude_none=False)),
                ),
            )
        assert service.put(approved, expected_version=1) == approved
        dispatched = dispatch_writeback(approved, policy=POLICY)
        assert service.put(dispatched, expected_version=2) == dispatched
        acknowledged = acknowledge_writeback(
            dispatched,
            provider_reference="synthetic-provider-reference",
            response_digest="b" * 64,
            acknowledged_at=NOW,
            accepted=True,
        )
        assert service.put(acknowledged, expected_version=3) == acknowledged
        current = service.get(intent_id=proposed.intent_id, tenant_id=tenant_id, workspace_id=workspace_id)
        assert current is not None
        assert current["version"] == 4
        assert current["intent"].status is WritebackStatus.ACKNOWLEDGED
        assert service.list_latest(tenant_id=tenant_id, workspace_id=workspace_id) == (acknowledged,)
        assert service.get(intent_id=proposed.intent_id, tenant_id="other-tenant", workspace_id=workspace_id) is None
        with pytest.raises(PostgresWritebackPersistenceError, match="version conflict"):
            service.put(dispatched, expected_version=3)
        with pytest.raises(psycopg.Error, match="immutable"), admin.transaction():
            admin.execute(
                "UPDATE reconforge.connector_writeback_intents SET status='failed' "
                "WHERE tenant_id=%s AND intent_id=%s",
                (tenant_id, proposed.intent_id),
            )
    finally:
        if connection is not None:
            connection.close()
        admin.close()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_erpnext_payment_writeback_history_is_scoped_and_replayable() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_id = "wberpnpay_" + uuid4().hex[:8]
    workspace_id = "workspace-erpnpay"
    admin = admin_factory.connect()
    connection = None
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_WRITEBACK_SCHEMA_SQL)
            admin.execute(POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                "GRANT SELECT, INSERT ON reconforge.connector_writeback_intents TO "
                f"{app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)",
                (tenant_id, tenant_id),
            )
        connection = factory.connect()
        repository = PostgresWritebackIntentRepository(connection)
        service = WritebackIntentApplicationService(repository)
        draft = ErpNextPaymentEntryDraft(
            company="Acme",
            posting_date="2026-08-11",
            paid_from="1100 - Cash",
            paid_to="2100 - Supplier Payables",
            paid_amount="125.00",
            received_amount="0.00",
            paid_from_account_currency="USD",
            paid_to_account_currency="USD",
            party_type="Supplier",
            party="SUP-001",
            reference_no="PAY-PG-001",
            remarks="Synthetic PostgreSQL Payment Entry draft",
        )
        payload = build_erpnext_payment_entry_payload(draft)
        policy = WritebackPolicy(
            connector_id="erpnext-payment-entry-writeback",
            allowed_operations=frozenset({ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION}),
            feature_enabled=True,
        )
        proposed = _intent(
            intent_id="erpnext-payment-pg-" + uuid4().hex[:16],
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            connector_id="erpnext-payment-entry-writeback",
            operation=ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION,
            payload_digest=payload.payload_digest,
            idempotency_key="erpnext-payment-pg-key-" + uuid4().hex[:12],
        )
        assert service.put(proposed) == proposed
        assert service.put(proposed) == proposed
        approved = approve_writeback(
            proposed,
            policy=policy,
            actor_id="checker-erpnpay",
            approved_at=NOW,
            assurance="mfa",
            reason="independent synthetic Payment Entry review",
        )
        assert service.put(approved, expected_version=1) == approved
        dispatched = dispatch_writeback(approved, policy=policy)
        assert service.put(dispatched, expected_version=2) == dispatched
        acknowledged = acknowledge_writeback(
            dispatched,
            provider_reference="synthetic-erpnext-payment-pg",
            response_digest="c" * 64,
            acknowledged_at=NOW,
            accepted=True,
        )
        assert service.put(acknowledged, expected_version=3) == acknowledged
        current = service.get(intent_id=proposed.intent_id, tenant_id=tenant_id, workspace_id=workspace_id)
        assert current is not None
        assert current["version"] == 4
        assert current["intent"].status is WritebackStatus.ACKNOWLEDGED
        assert current["intent"].operation == ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION
        assert current["intent"].payload_digest == payload.payload_digest
        assert service.get(intent_id=proposed.intent_id, tenant_id="other-tenant", workspace_id=workspace_id) is None
        with pytest.raises(PostgresWritebackPersistenceError, match="version conflict"):
            service.put(dispatched, expected_version=3)
        with pytest.raises(psycopg.Error, match="immutable"), admin.transaction():
            admin.execute(
                "UPDATE reconforge.connector_writeback_intents SET status='failed' "
                "WHERE tenant_id=%s AND intent_id=%s",
                (tenant_id, proposed.intent_id),
            )
    finally:
        if connection is not None:
            connection.close()
        admin.close()
