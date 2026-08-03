from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest

from reconforge.application.consolidation_ppa import AcquisitionPpaApplicationService
from reconforge.domain.consolidation_ppa import AcquisitionPpaItem, AcquisitionPurchasePriceAllocationRequest
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_consolidation_ppa import (
    PostgresConsolidationPpaError,
    PostgresConsolidationPpaRepository,
)
from reconforge.utils.money import Money


def _money(value: str) -> Money:
    return Money.from_exact(Decimal(value), "USD", strict_precision=True)


def _request(suffix: str, *, prepared_by: str, approved_by: str) -> AcquisitionPurchasePriceAllocationRequest:
    return AcquisitionPurchasePriceAllocationRequest(
        acquisition_id=f"ACQ-{suffix}",
        subsidiary_entity_code=f"SUB-{suffix}",
        period_id="2026-Q3",
        acquisition_date="2026-07-01",
        reporting_currency="USD",
        consideration=_money("170.00"),
        nci_fair_value=_money("30.00"),
        items=(
            AcquisitionPpaItem(
                item_id="asset-001",
                item_kind="asset",
                class_code="PROPERTY",
                account_code="PROPERTY-FV",
                book_value=_money("100.00"),
                fair_value=_money("125.00"),
                valuation_reference="valuation-property-001",
                source_reference="valuation-pack-001",
            ),
            AcquisitionPpaItem(
                item_id="liability-001",
                item_kind="liability",
                class_code="DEBT",
                account_code="DEBT-FV",
                book_value=_money("30.00"),
                fair_value=_money("35.00"),
                valuation_reference="valuation-debt-001",
                source_reference="valuation-pack-001",
            ),
        ),
        allow_bargain_purchase=False,
        consideration_account_code="CONSIDERATION",
        nci_account_code="NCI",
        identifiable_net_assets_account_code="NET-ASSETS",
        goodwill_account_code="GOODWILL",
        bargain_purchase_account_code="BARGAIN",
        policy_id="PPA-POLICY",
        policy_version="1.0.0",
        source_reference="purchase-agreement-ppa-001",
        source_digest="a" * 64,
        prepared_by=prepared_by,
        prepared_at="2026-07-01T12:00:00Z",
        approved_by=approved_by,
        approved_at="2026-07-01T11:00:00Z",
    )


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_ppa_persistence_is_replayable_immutable_and_tenant_isolated() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER must name the non-privileged test role")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    suffix = uuid4().hex[:10]
    tenant_a = f"ppa_a_{suffix}"
    tenant_b = f"ppa_b_{suffix}"
    user_one = f"ppa_preparer_{suffix}"
    user_two = f"ppa_reviewer_{suffix}"

    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT ON TABLE reconforge.consolidation_ppa_artifacts, "
                f"reconforge.identity_users, reconforge.domain_audit_events TO {app_user}; "
                f"GRANT SELECT, INSERT, UPDATE ON TABLE reconforge.domain_audit_ledger_state TO {app_user}"
            )
            admin.execute(
                """INSERT INTO reconforge.identity_users
                   (tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm)
                   VALUES (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),
                          (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),
                          (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),
                          (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256')""",
                (
                    tenant_a, user_one, user_one, user_one,
                    tenant_a, user_two, user_two, user_two,
                    tenant_b, user_one, user_one, user_one,
                    tenant_b, user_two, user_two, user_two,
                ),
            )

        request = _request(suffix, prepared_by=user_one, approved_by=user_two)
        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            service = AcquisitionPpaApplicationService(PostgresConsolidationPpaRepository(connection, tenant_a))
            created = service.prepare_and_persist(request, actor_label=user_one)
            repeated = service.prepare_and_persist(request, actor_label=user_one)
            loaded = service.get(str(created["id"]), actor_label=user_one)
            assert repeated["id"] == created["id"]
            assert loaded["result_digest"] == created["result_digest"]
            assert loaded["result_payload"]["posted"] is False

        with pytest.raises(PostgresConsolidationPpaError, match="not found"), PostgresTenantBoundary(
            app_factory
        ).transaction(tenant_b) as connection:
            AcquisitionPpaApplicationService(PostgresConsolidationPpaRepository(connection, tenant_b)).get(
                str(created["id"]), actor_label=user_one
            )

        with pytest.raises(Exception, match="consolidation PPA artifacts are immutable"), admin.transaction():
            admin.execute(
                "UPDATE reconforge.consolidation_ppa_artifacts SET acquisition_id=%s WHERE tenant_id=%s AND id=%s",
                ("tampered", tenant_a, created["id"]),
            )
        with pytest.raises(Exception, match="consolidation PPA artifacts cannot be deleted"), admin.transaction():
            admin.execute(
                "DELETE FROM reconforge.consolidation_ppa_artifacts WHERE tenant_id=%s AND id=%s",
                (tenant_a, created["id"]),
            )
    finally:
        with admin.transaction():
            admin.execute(
                "ALTER TABLE reconforge.consolidation_ppa_artifacts DISABLE TRIGGER consolidation_ppa_artifact_guard"
            )
            admin.execute(
                "DELETE FROM reconforge.consolidation_ppa_artifacts WHERE tenant_id IN (%s,%s)",
                (tenant_a, tenant_b),
            )
            admin.execute(
                "ALTER TABLE reconforge.consolidation_ppa_artifacts ENABLE TRIGGER consolidation_ppa_artifact_guard"
            )
            admin.execute(
                "ALTER TABLE reconforge.domain_audit_events DISABLE TRIGGER domain_audit_events_immutable"
            )
            admin.execute(
                "DELETE FROM reconforge.domain_audit_events WHERE tenant_id IN (%s,%s)",
                (tenant_a, tenant_b),
            )
            admin.execute(
                "ALTER TABLE reconforge.domain_audit_events ENABLE TRIGGER domain_audit_events_immutable"
            )
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        admin.close()
