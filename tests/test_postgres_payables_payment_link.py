"""Nonowner PostgreSQL contracts for immutable AP settlement evidence."""

from __future__ import annotations

import ast
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.payables_payment_link import payment_external_reference
from reconforge.infrastructure.postgres import _HybridPostgresRow
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_payables_payment_link import (
    PostgresPayablesPaymentLinkRepository,
    _row,
)
from reconforge.platform.common import PlatformError, ServerPrincipal, server_principal_context
from reconforge.platform.payables import PurchaseOrderLineInput, SupplierInvoiceLineInput

pytest_plugins = ("tests.test_postgres_finance_scope",)

PERMISSIONS = frozenset(
    {"finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post", "payables.settle"}
)
MAKER = PostingActor("payment-maker", "payment-maker", PERMISSIONS, step_up_active=True)
CHECKER = PostingActor("payment-checker", "payment-checker", PERMISSIONS, step_up_active=True)
POSTER = PostingActor("payment-poster", "payment-poster", PERMISSIONS, step_up_active=True)
SETTLER = PostingActor("payment-settler", "payment-settler", PERMISSIONS, step_up_active=True)
SCOPE = {"organization_id": "org_a", "workspace_id": "shared", "legal_entity_id": "entity_a1"}


def _principal(actor: PostingActor) -> ServerPrincipal:
    return ServerPrincipal(
        LocalUser(id=actor.user_id, username=actor.username, display_name=actor.username),
        PERMISSIONS,
        step_up_active=True,
    )


def _migration_assignments(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in {"revision", "down_revision", "UPGRADE_SQL", "DOWNGRADE_SQL"}
    }


def test_payment_link_postgres_migration_is_frozen_and_scope_guarded() -> None:
    values = _migration_assignments(Path("alembic/versions/0105_postgres_payables_payment_link.py"))
    assert values["revision"] == "0105_pg_payables_payment_link"
    assert values["down_revision"] == "0104_pg_exception_review_api"
    upgrade = str(values["UPGRADE_SQL"])
    downgrade = str(values["DOWNGRADE_SQL"])
    assert "UNIQUE(tenant_id,supplier_invoice_id,invoice_version_before)" in upgrade
    assert "FOR NO KEY UPDATE" in upgrade
    assert "NEW.invoice_version_before<>invoice.row_version" in upgrade
    assert "ap_payment_link_invoice_transition" in upgrade
    assert upgrade.count("FORCE ROW LEVEL SECURITY") == 2
    assert "Supplier payment evidence prevents downgrade" in downgrade


def test_payment_link_adapter_decodes_runtime_hybrid_rows_by_name() -> None:
    source = _HybridPostgresRow(("id", "amount_minor", "currency_code"), ("APPAY-1", 400, "EGP"))
    assert _row(source) == {"id": "APPAY-1", "amount_minor": 400, "currency_code": "EGP"}


@pytest.fixture
def payment_link_database(finance_database: dict[str, Any]) -> dict[str, Any]:
    """Add 0105 grants and independently identifiable actors after head upgrade."""

    import psycopg

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a nonowner PostgreSQL application DSN")
    role = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
    with psycopg.connect(finance_database["admin"], autocommit=True) as admin:
        identifier = psycopg.sql.Identifier(role)
        admin.execute(
            psycopg.sql.SQL(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.ap_payment_links,"
                "reconforge.ap_payment_link_commands TO {}"
            ).format(identifier)
        )
        for actor in (MAKER, CHECKER, POSTER, SETTLER):
            admin.execute(
                """INSERT INTO reconforge.identity_users
                   (tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm)
                   VALUES ('finance_scope',%s,%s,%s,'x','x',100000,'pbkdf2_sha256')
                   ON CONFLICT (tenant_id,id) DO NOTHING""",
                (actor.user_id, actor.username, actor.username),
            )
    return finance_database


def _approved_invoice(connection: Any, *, suffix: str) -> dict[str, Any]:
    payables = PostgresPayablesRepository(connection, "finance_scope")
    payables.upsert_supplier(
        supplier_code=f"SUP-{suffix}",
        name="Synthetic settlement supplier",
        currency_code="EGP",
        workspace="Shared",
        organization_code="ORG_A",
        entity_code="A1",
        actor_label=MAKER.user_id,
    )
    order = payables.create_purchase_order(
        po_number=f"PO-{suffix}",
        supplier_code=f"SUP-{suffix}",
        order_date="2026-07-21",
        currency_code="EGP",
        lines=[PurchaseOrderLineInput(item_code=f"ITEM-{suffix}", ordered_quantity="1", unit_price_minor=1_000)],
        workspace="Shared",
        organization_code="ORG_A",
        entity_code="A1",
        actor_label=MAKER.user_id,
    )
    order = payables.submit_purchase_order(order["id"], expected_version=1, actor_label=MAKER.user_id)
    order = payables.approve_purchase_order(order["id"], expected_version=2, actor_label=CHECKER.user_id)
    receipt = payables.post_receipt(
        receipt_number=f"GR-{suffix}",
        purchase_order_id=order["id"],
        receipt_date="2026-07-22",
        quantities={str(order["lines"][0]["id"]): "1"},
        workspace="Shared",
        actor_label=MAKER.user_id,
    )
    assert receipt["status"] == "Posted"
    invoice = payables.create_supplier_invoice(
        invoice_number=f"INV-{suffix}",
        supplier_code=f"SUP-{suffix}",
        invoice_date="2026-07-23",
        currency_code="EGP",
        total_minor=1_000,
        lines=[
            SupplierInvoiceLineInput(
                purchase_order_line_id=str(order["lines"][0]["id"]),
                invoiced_quantity="1",
                unit_price_minor=1_000,
                line_total_minor=1_000,
            )
        ],
        purchase_order_id=order["id"],
        workspace="Shared",
        organization_code="ORG_A",
        entity_code="A1",
        actor_label=MAKER.user_id,
    )
    invoice = payables.submit_supplier_invoice(invoice["id"], expected_version=1, actor_label=MAKER.user_id)
    assert payables.run_three_way_match(invoice["id"], actor_label=MAKER.user_id).status == "Passed"
    return payables.approve_supplier_invoice(invoice["id"], expected_version=3, actor_label=CHECKER.user_id)


def _payment_effect(
    connection: Any,
    *,
    invoice_id: str,
    amount_minor: int,
    suffix: str,
) -> dict[str, Any]:
    finance = PostgresFinanceCoreRepository(connection, "finance_scope")
    finance.upsert_account(
        account_code="A_AP",
        name="Accounts payable",
        workspace="Shared",
        chart_code="A",
        account_type="Liability",
        normal_balance="Credit",
    )
    amount = f"{amount_minor // 100}.{amount_minor % 100:02d}"
    with server_principal_context(_principal(MAKER)):
        entry = finance.create_entry(
            entry_number=f"PAY-{suffix}",
            organization_code="ORG_A",
            entity_code="A1",
            period_id="period",
            journal_code="J_A",
            posting_date="2026-07-24",
            description="Synthetic independently reviewed AP settlement",
            external_reference=payment_external_reference(invoice_id),
            workspace="Shared",
            actor_label=MAKER.user_id,
            lines=[
                {"account_code": "A_AP", "debit": amount, "dimensions": {"D_A": "V", "D_SHARED": "V"}},
                {"account_code": "A_CASH", "credit": amount, "dimensions": {"D_A": "V", "D_SHARED": "V"}},
            ],
        )
    with server_principal_context(_principal(CHECKER)):
        finance.validate_entry(entry["id"], reason="Independent settlement review", actor_label=CHECKER.user_id)
    posting = PostgresFinancePostingRepository(connection, "finance_scope")
    preview = posting.preview(entry["id"], actor=POSTER)
    return posting.post(
        entry["id"],
        command_id=f"post-{suffix}",
        expected_validation_digest=preview["current_content_digest"],
        reason="Independent settlement posting",
        actor=POSTER,
    )


def _account_ids(connection: Any) -> dict[str, str]:
    return {
        str(row["account_code"]): str(row["id"])
        for row in connection.execute(
            "SELECT account_code,id FROM reconforge.finance_accounts "
            "WHERE tenant_id='finance_scope' AND account_code IN ('A_AP','A_CASH')"
        ).fetchall()
    }


def test_live_payment_link_nonowner_replays_hybrid_rows_and_retained_evidence(
    payment_link_database: dict[str, Any],
) -> None:
    import psycopg

    db = payment_link_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        assert tuple(
            connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        ) == (False, False)
        invoice = _approved_invoice(connection, suffix="PG-LINK")
        first_effect = _payment_effect(connection, invoice_id=invoice["id"], amount_minor=400, suffix="PG-LINK-400")
        accounts = _account_ids(connection)
        links = PostgresPayablesPaymentLinkRepository(connection, "finance_scope")
        assert links.authorization_amount(
            invoice["id"],
            finance_effect_id=first_effect["id"],
            ap_account_id=accounts["A_AP"],
            cash_account_id=accounts["A_CASH"],
            actor_label=SETTLER.user_id,
        ) == Decimal(400)
        first = links.link_finance_payment(
            invoice["id"],
            finance_effect_id=first_effect["id"],
            ap_account_id=accounts["A_AP"],
            cash_account_id=accounts["A_CASH"],
            expected_invoice_version=invoice["row_version"],
            command_id="settle-400",
            actor_label=SETTLER.user_id,
        )
        assert links.link_finance_payment(
            invoice["id"],
            finance_effect_id=first_effect["id"],
            ap_account_id=accounts["A_AP"],
            cash_account_id=accounts["A_CASH"],
            expected_invoice_version=invoice["row_version"],
            command_id="settle-400",
            actor_label=SETTLER.user_id,
        ) == first
        current = PostgresPayablesRepository(connection, "finance_scope").get_supplier_invoice(invoice["id"])
        second_effect = _payment_effect(connection, invoice_id=invoice["id"], amount_minor=600, suffix="PG-LINK-600")
        second = links.link_finance_payment(
            invoice["id"],
            finance_effect_id=second_effect["id"],
            ap_account_id=accounts["A_AP"],
            cash_account_id=accounts["A_CASH"],
            expected_invoice_version=current["row_version"],
            command_id="settle-600",
            actor_label=SETTLER.user_id,
        )
        assert (first["allocated_minor"], first["invoice_status"]) == (400, "Approved")
        assert (second["allocated_minor"], second["invoice_status"]) == (1_000, "Paid")
        assert [link["amount_minor"] for link in links.list_payment_links(invoice["id"])] == [400, 600]
        assert connection.execute(
            "SELECT count(*) FROM reconforge.ap_payment_link_commands WHERE tenant_id='finance_scope'"
        ).fetchone()[0] == 2
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "UPDATE reconforge.ap_payment_links SET amount_minor=1 WHERE tenant_id='finance_scope' AND id=%s",
                (first["payment_link_id"],),
            )


def test_live_payment_link_concurrent_full_allocations_admit_one(
    payment_link_database: dict[str, Any],
) -> None:
    db = payment_link_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        invoice = _approved_invoice(connection, suffix="PG-RACE")
        first_effect = _payment_effect(connection, invoice_id=invoice["id"], amount_minor=600, suffix="PG-RACE-A")
        second_effect = _payment_effect(connection, invoice_id=invoice["id"], amount_minor=600, suffix="PG-RACE-B")
        accounts = _account_ids(connection)

    barrier = Barrier(2)

    def attempt(effect: dict[str, Any], command: str) -> str:
        try:
            barrier.wait(timeout=10)
            with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
                return str(
                    PostgresPayablesPaymentLinkRepository(connection, "finance_scope").link_finance_payment(
                        invoice["id"],
                        finance_effect_id=effect["id"],
                        ap_account_id=accounts["A_AP"],
                        cash_account_id=accounts["A_CASH"],
                        expected_invoice_version=invoice["row_version"],
                        command_id=command,
                        actor_label=SETTLER.user_id,
                    )["payment_link_id"]
                )
        except PlatformError as exc:
            return f"error:{exc}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda input_value: attempt(*input_value), ((first_effect, "race-a"), (second_effect, "race-b"))))
    assert sum(not outcome.startswith("error:") for outcome in outcomes) == 1
