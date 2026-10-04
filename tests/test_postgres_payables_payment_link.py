"""Nonowner PostgreSQL contracts for immutable AP settlement evidence."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

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
ROOT = Path(__file__).resolve().parents[1]
PAYMENT_LINK_PREVIOUS_REVISION = "0104_pg_exception_review_api"
PAYMENT_LINK_CURRENT_REVISION = "0105_pg_payables_payment_link"


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
    assert upgrade.lstrip().startswith("DO $payment$")
    assert downgrade.lstrip().startswith("DO $payment$")
    assert upgrade.count("rolsuper OR rolbypassrls") == 1
    assert downgrade.count("rolsuper OR rolbypassrls") == 1
    assert "payables payment-link migration requires a role that bypasses forced row security" in upgrade
    assert "payables payment-link migration requires a role that bypasses forced row security" in downgrade
    assert "UNIQUE(tenant_id,supplier_invoice_id,invoice_version_before)" in upgrade
    assert "FOR NO KEY UPDATE" in upgrade
    assert "NEW.invoice_version_before<>invoice.row_version" in upgrade
    assert "NEW.status<>(CASE WHEN allocated=OLD.total_minor THEN 'Paid' ELSE 'Approved' END)" in upgrade
    assert "invoice.created_by IS NULL OR btrim(invoice.created_by)=''" in upgrade
    assert "invoice.approved_by IS NULL OR btrim(invoice.approved_by)=''" in upgrade
    assert "ap_payment_link_invoice_transition" in upgrade
    assert upgrade.count("FORCE ROW LEVEL SECURITY") == 2
    assert "Supplier payment evidence prevents downgrade" in downgrade


def test_payment_link_adapter_decodes_runtime_hybrid_rows_by_name() -> None:
    source = _HybridPostgresRow(("id", "amount_minor", "currency_code"), ("APPAY-1", 400, "EGP"))
    assert _row(source) == {"id": "APPAY-1", "amount_minor": 400, "currency_code": "EGP"}


def test_payment_link_authorization_amount_reuses_retained_full_payment_receipt() -> None:
    class ReplayOnlyRepository(PostgresPayablesPaymentLinkRepository):
        def __init__(self) -> None:
            self.tenant_id = "finance_scope"
            self.effect_read = False
            self.replay_arguments: dict[str, object] = {}

        @contextmanager
        def _transaction(self) -> Iterator[None]:
            yield

        def _assert_current_actor(self, actor_id: str) -> None:
            assert actor_id == SETTLER.user_id

        def _invoice(self, invoice_id: str, *, lock: bool = False) -> dict[str, object]:
            assert invoice_id == "invoice-paid"
            assert not lock
            return {"id": invoice_id, "workspace_id": "shared", "status": "Paid"}

        def _replay_if_present(self, **arguments: object) -> dict[str, object] | None:
            self.replay_arguments = arguments
            return {"amount_minor": 1_000}

        def _effect(self, effect_id: str) -> dict[str, object]:
            self.effect_read = True
            raise AssertionError("a retained full-payment retry must not revalidate a Paid invoice")

    repository = ReplayOnlyRepository()
    assert repository.authorization_amount(
        "invoice-paid",
        finance_effect_id="effect-paid",
        ap_account_id="account-ap",
        cash_account_id="account-cash",
        expected_invoice_version=4,
        command_id="settle-paid",
        actor_label=SETTLER.user_id,
    ) == Decimal(1_000)
    assert repository.replay_arguments["workspace_id"] == "shared"
    assert repository.replay_arguments["command_id"] == "settle-paid"
    assert not repository.effect_read


def _migrate_payment_link_revision(
    dsn: str,
    action: str,
    target: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", action, target],
        cwd=ROOT,
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def payment_link_prior_database() -> Iterator[str]:
    """Create a disposable database whose registered head is exactly 0104."""

    import psycopg
    from psycopg import sql

    database = "reconforge_payment_link_migration_" + uuid4().hex[:12]
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
        result = _migrate_payment_link_revision(admin_dsn, "upgrade", PAYMENT_LINK_PREVIOUS_REVISION)
        assert result.returncode == 0, result.stderr
        yield admin_dsn
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None


def _payment_link_current_revision(connection: object) -> str:
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()  # type: ignore[attr-defined]
    assert row is not None
    return str(row[0])


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="requires an owned live PostgreSQL administrator DSN",
)
def test_live_payment_link_migration_rejects_non_bypass_role_before_partial_mutation(
    payment_link_prior_database: str,
) -> None:
    """Neither direction may inspect, seed, or drop forced-RLS evidence as an app role."""

    import psycopg
    from psycopg import sql

    role_name = "payment_link_migration_" + uuid4().hex[:12]
    role_password = "Synthetic-payment-link-migration-123"
    control_dsn = psycopg.conninfo.make_conninfo(
        os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"],
        dbname="postgres",
        connect_timeout=5,
    )
    parsed_prior_dsn = urlsplit(payment_link_prior_database)
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
        with psycopg.connect(payment_link_prior_database, autocommit=True) as administrator:
            administrator.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(parsed_prior_dsn.path.lstrip("/")),
                    sql.Identifier(role_name),
                )
            )
            administrator.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(role_name)))
            administrator.execute(sql.SQL("GRANT SELECT ON alembic_version TO {}").format(sql.Identifier(role_name)))

        rejected_upgrade = _migrate_payment_link_revision(
            low_dsn,
            "upgrade",
            PAYMENT_LINK_CURRENT_REVISION,
        )
        assert rejected_upgrade.returncode != 0
        assert "payables payment-link migration requires a role that bypasses forced row security" in (
            rejected_upgrade.stdout + rejected_upgrade.stderr
        )
        with psycopg.connect(payment_link_prior_database, autocommit=True) as administrator:
            assert _payment_link_current_revision(administrator) == PAYMENT_LINK_PREVIOUS_REVISION
            assert administrator.execute("SELECT to_regclass('reconforge.ap_payment_links')").fetchone() == (None,)
            assert administrator.execute("SELECT to_regclass('reconforge.ap_payment_link_commands')").fetchone() == (None,)
            assert administrator.execute(
                "SELECT count(*) FROM reconforge.identity_permissions WHERE name='payables.settle'"
            ).fetchone() == (0,)

        accepted_upgrade = _migrate_payment_link_revision(
            payment_link_prior_database,
            "upgrade",
            PAYMENT_LINK_CURRENT_REVISION,
        )
        assert accepted_upgrade.returncode == 0, accepted_upgrade.stderr
        rejected_downgrade = _migrate_payment_link_revision(
            low_dsn,
            "downgrade",
            PAYMENT_LINK_PREVIOUS_REVISION,
        )
        assert rejected_downgrade.returncode != 0
        assert "payables payment-link migration requires a role that bypasses forced row security" in (
            rejected_downgrade.stdout + rejected_downgrade.stderr
        )
        with psycopg.connect(payment_link_prior_database, autocommit=True) as administrator:
            assert _payment_link_current_revision(administrator) == PAYMENT_LINK_CURRENT_REVISION
            assert administrator.execute("SELECT to_regclass('reconforge.ap_payment_links')").fetchone() == (
                "reconforge.ap_payment_links",
            )
            assert administrator.execute("SELECT to_regclass('reconforge.ap_payment_link_commands')").fetchone() == (
                "reconforge.ap_payment_link_commands",
            )
    finally:
        with psycopg.connect(payment_link_prior_database, autocommit=True) as administrator:
            administrator.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name)))


@pytest.fixture
def payment_link_database(finance_database: dict[str, Any]) -> dict[str, Any]:
    """Add 0105 grants and independently identifiable actors after head upgrade."""

    import psycopg

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a nonowner PostgreSQL application DSN")
    role = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
    if not isinstance(role, str) or not role:
        raise AssertionError("the nonowner PostgreSQL application DSN must identify its role")
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
    # Finance reference maintenance is intentionally permitted at the
    # organization/workspace boundary, but not from an entity-scoped payment
    # transaction.  Provision the AP account at that broader boundary so the
    # settlement tests exercise the same separation as a real deployment.
    with finance_database["boundary"].transaction(
        "finance_scope",
        workspace_id=SCOPE["workspace_id"],
        organization_id=SCOPE["organization_id"],
    ) as connection:
        PostgresFinanceCoreRepository(connection, "finance_scope").upsert_account(
            account_code="A_AP",
            name="Accounts payable",
            workspace="Shared",
            chart_code="A",
            account_type="Liability",
            normal_balance="Credit",
            actor_label=POSTER.user_id,
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
            expected_invoice_version=invoice["row_version"],
            command_id="settle-400",
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
        assert links.authorization_amount(
            invoice["id"],
            finance_effect_id=second_effect["id"],
            ap_account_id=accounts["A_AP"],
            cash_account_id=accounts["A_CASH"],
            expected_invoice_version=current["row_version"],
            command_id="settle-600",
            actor_label=SETTLER.user_id,
        ) == Decimal(600)
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
