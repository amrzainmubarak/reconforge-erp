"""PostgreSQL contracts for immutable Finance-evidenced AP payment unwinds."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_payables_payment_link import PostgresPayablesPaymentLinkRepository
from reconforge.platform.common import PlatformError, server_principal_context
from tests.postgres_test_hygiene import PAYABLES_TENANT_CLEANUP_PLAN
from tests.test_postgres_payables_payment_link import (
    CHECKER,
    MAKER,
    POSTER,
    REVERSER,
    SCOPE,
    SETTLER,
    _account_ids,
    _approved_invoice,
    _payment_effect,
    _principal,
)

pytest_plugins = ("tests.test_postgres_payables_payment_link",)


def _migration_values() -> dict[str, object]:
    path = Path("alembic/versions/0106_postgres_ap_link_reversal.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id in {"revision", "down_revision", "UPGRADE_SQL", "DOWNGRADE_SQL"}
    }


def test_payment_link_reversal_migration_is_scoped_immutable_and_loss_refusing() -> None:
    values = _migration_values()
    upgrade = str(values["UPGRADE_SQL"])
    downgrade = str(values["DOWNGRADE_SQL"])
    assert values["revision"] == "0106_pg_ap_link_reversal"
    assert values["down_revision"] == "0105_pg_payables_payment_link"
    assert upgrade.lstrip().startswith("DO $reversal$")
    assert downgrade.lstrip().startswith("DO $reversal$")
    assert upgrade.count("rolsuper OR rolbypassrls") == 1
    assert downgrade.count("rolsuper OR rolbypassrls") == 1
    assert "payables payment-link reversal migration requires a role that bypasses forced row security" in upgrade
    assert "payables payment-link reversal migration requires a role that bypasses forced row security" in downgrade
    assert "UNIQUE(tenant_id,payment_link_id)" in upgrade
    assert "UNIQUE(tenant_id,reversal_finance_effect_id)" in upgrade
    assert "UNIQUE(tenant_id,supplier_invoice_id,invoice_version_before)" in upgrade
    assert "FOR NO KEY UPDATE" in upgrade
    assert "finance_effect.source_kind<>'Reversal'" in upgrade
    assert "finance_effect.reverses_effect_id<>link.finance_effect_id" in upgrade
    assert "reversal_actor_id IN" in upgrade
    assert "payment_link_canonical_principal_id" in upgrade
    assert "id=btrim(input_actor) OR username=btrim(input_actor)" in upgrade
    assert "array_length(candidate_ids,1)" in upgrade
    assert "original_finance_effect" in upgrade
    assert "DROP FUNCTION reconforge.payment_link_canonical_principal_id(TEXT,TEXT)" in downgrade
    assert upgrade.count("FORCE ROW LEVEL SECURITY") == 2
    assert "ap_payment_link_reversal_command_guard" in upgrade
    assert "reversal.invoice_version_before<=link.invoice_version_before" in upgrade
    assert "prevents downgrade" in downgrade
    assert "ap_payment_link_reversals" in downgrade


def test_payment_link_reversal_cleanup_deletes_children_before_evidence() -> None:
    tables = [table.name for table in PAYABLES_TENANT_CLEANUP_PLAN.tables]
    assert tables.index("ap_payment_link_reversal_commands") < tables.index("ap_payment_link_reversals")
    assert tables.index("ap_payment_link_reversals") < tables.index("ap_payment_link_commands")
    assert tables.index("ap_payment_link_reversals") < tables.index("domain_audit_events")
    immutable = {
        (trigger.table_name, trigger.trigger_name)
        for trigger in PAYABLES_TENANT_CLEANUP_PLAN.immutable_triggers
    }
    assert ("ap_payment_link_reversals", "ap_payment_link_reversal_guard") in immutable
    assert (
        "ap_payment_link_reversal_commands",
        "ap_payment_link_reversal_command_guard",
    ) in immutable


def _reversal_effect(
    connection: Any,
    *,
    original_effect_id: str,
    period_id: str,
    suffix: str,
) -> dict[str, Any]:
    posting = PostgresFinancePostingRepository(connection, "finance_scope")
    with server_principal_context(_principal(MAKER)):
        draft = posting.prepare_reversal(
            original_effect_id,
            command_id=f"prepare-{suffix}",
            entry_number=f"REV-{suffix}",
            period_id=period_id,
            posting_date="2026-07-25",
            reason="Synthetic independently reviewed AP allocation correction",
            actor=MAKER,
        )
    with server_principal_context(_principal(CHECKER)):
        PostgresFinanceCoreRepository(connection, "finance_scope").validate_entry(
            draft["entry_id"],
            reason="Independent reversal review",
            actor_label=CHECKER.user_id,
        )
    with server_principal_context(_principal(POSTER)):
        preview = posting.preview(draft["entry_id"], actor=POSTER)
        return posting.post(
            draft["entry_id"],
            command_id=f"post-{suffix}",
            expected_validation_digest=preview["current_content_digest"],
            reason="Independent reversal posting",
            actor=POSTER,
        )


def test_live_payment_link_identity_alias_collision_fails_closed(
    payment_link_database: dict[str, Any],
) -> None:
    """A text that names two principals must never select one for SoD checks."""

    import psycopg

    db = payment_link_database
    alias = "alias-collision-principal"
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        admin.execute(
            """INSERT INTO reconforge.identity_users
               (tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm)
               VALUES ('finance_scope',%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),
                      ('finance_scope',%s,%s,%s,'x','x',100000,'pbkdf2_sha256')""",
            (
                alias,
                "alias-collision-source",
                "Alias collision source",
                "alias-collision-other",
                alias,
                "Alias collision target",
            ),
        )
    try:
        with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
            repository = PostgresPayablesPaymentLinkRepository(connection, "finance_scope")
            assert repository._canonical_principal_id(
                SETTLER.username, field="Settlement actor id"
            ) == SETTLER.user_id
            with pytest.raises(PlatformError, match="does not resolve to one tenant principal"):
                repository._canonical_principal_id(alias, field="Settlement actor id")
            assert connection.execute(
                "SELECT reconforge.payment_link_canonical_principal_id(%s,%s)",
                ("finance_scope", alias),
            ).fetchone()[0] is None
    finally:
        with psycopg.connect(db["admin"], autocommit=True) as admin:
            admin.execute(
                """DELETE FROM reconforge.identity_users
                   WHERE tenant_id='finance_scope' AND id IN (%s,%s)""",
                (alias, "alias-collision-other"),
            )


def test_live_payment_link_reversal_requires_posted_inverse_and_retains_historical_receipt(
    payment_link_database: dict[str, Any],
) -> None:
    import psycopg

    db = payment_link_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        invoice = _approved_invoice(connection, suffix="PG-REV")
        original = _payment_effect(connection, invoice_id=invoice["id"], amount_minor=1_000, suffix="PG-REV")
        accounts = _account_ids(connection)
        links = PostgresPayablesPaymentLinkRepository(connection, "finance_scope")
        linked = links.link_finance_payment(
            invoice["id"],
            finance_effect_id=original["id"],
            ap_account_id=accounts["A_AP"],
            cash_account_id=accounts["A_CASH"],
            expected_invoice_version=invoice["row_version"],
            command_id="settle-reversal-source",
            actor_label=SETTLER.user_id,
        )
        current = PostgresPayablesRepository(connection, "finance_scope").get_supplier_invoice(invoice["id"])
        inverse = _reversal_effect(
            connection,
            original_effect_id=original["id"],
            period_id="period",
            suffix="PG-REV-INVERSE",
        )
        assert links.authorization_reversal_amount(
            invoice["id"],
            payment_link_id=linked["payment_link_id"],
            reversal_finance_effect_id=inverse["id"],
            expected_invoice_version=current["row_version"],
            command_id="reverse-payment-link",
            actor_label=REVERSER.user_id,
        ) == Decimal(1_000)
        reversed_result = links.reverse_finance_payment_link(
            invoice["id"],
            linked["payment_link_id"],
            reversal_finance_effect_id=inverse["id"],
            expected_invoice_version=current["row_version"],
            command_id="reverse-payment-link",
            actor_label=REVERSER.user_id,
        )
        assert reversed_result["allocated_minor"] == 0
        assert reversed_result["invoice_status"] == "Approved"
        assert links.reverse_finance_payment_link(
            invoice["id"],
            linked["payment_link_id"],
            reversal_finance_effect_id=inverse["id"],
            expected_invoice_version=current["row_version"],
            command_id="reverse-payment-link",
            actor_label=REVERSER.user_id,
        ) == reversed_result
        after_reversal = PostgresPayablesRepository(connection, "finance_scope").get_supplier_invoice(invoice["id"])
        replacement = _payment_effect(
            connection,
            invoice_id=invoice["id"],
            amount_minor=1_000,
            suffix="PG-REV-REPLACEMENT",
        )
        assert links.link_finance_payment(
            invoice["id"],
            finance_effect_id=replacement["id"],
            ap_account_id=accounts["A_AP"],
            cash_account_id=accounts["A_CASH"],
            expected_invoice_version=after_reversal["row_version"],
            command_id="settle-after-reversal",
            actor_label=SETTLER.user_id,
        )["invoice_status"] == "Paid"
        assert links.reverse_finance_payment_link(
            invoice["id"],
            linked["payment_link_id"],
            reversal_finance_effect_id=inverse["id"],
            expected_invoice_version=current["row_version"],
            command_id="reverse-payment-link",
            actor_label=REVERSER.user_id,
        ) == reversed_result
        assert [row["payment_link_id"] for row in links.list_payment_link_reversals(invoice["id"])] == [
            linked["payment_link_id"]
        ]
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "DELETE FROM reconforge.ap_payment_link_reversals WHERE tenant_id='finance_scope'"
            )


def test_live_payment_link_reversal_concurrent_commands_admit_one_effect(
    payment_link_database: dict[str, Any],
) -> None:
    db = payment_link_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        invoice = _approved_invoice(connection, suffix="PG-REV-RACE")
        original = _payment_effect(connection, invoice_id=invoice["id"], amount_minor=1_000, suffix="PG-REV-RACE")
        accounts = _account_ids(connection)
        linked = PostgresPayablesPaymentLinkRepository(connection, "finance_scope").link_finance_payment(
            invoice["id"],
            finance_effect_id=original["id"],
            ap_account_id=accounts["A_AP"],
            cash_account_id=accounts["A_CASH"],
            expected_invoice_version=invoice["row_version"],
            command_id="settle-reversal-race",
            actor_label=SETTLER.user_id,
        )
        inverse = _reversal_effect(
            connection,
            original_effect_id=original["id"],
            period_id="period",
            suffix="PG-REV-RACE-INVERSE",
        )
        current = PostgresPayablesRepository(connection, "finance_scope").get_supplier_invoice(invoice["id"])

    barrier = Barrier(2)

    def attempt(command: str) -> str:
        barrier.wait(timeout=15)
        try:
            with (
                db["boundary"].transaction("finance_scope", **SCOPE) as connection,
                server_principal_context(_principal(REVERSER)),
            ):
                return str(
                    PostgresPayablesPaymentLinkRepository(
                        connection, "finance_scope"
                    ).reverse_finance_payment_link(
                        invoice["id"],
                        linked["payment_link_id"],
                        reversal_finance_effect_id=inverse["id"],
                        expected_invoice_version=current["row_version"],
                        command_id=command,
                        actor_label=REVERSER.user_id,
                    )["payment_link_reversal_id"]
                )
        except PlatformError as exc:
            return f"error:{exc}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, ("reverse-race-a", "reverse-race-b")))
    assert sum(not result.startswith("error:") for result in outcomes) == 1
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        assert connection.execute(
            "SELECT count(*) FROM reconforge.ap_payment_link_reversals WHERE tenant_id='finance_scope'"
        ).fetchone()[0] == 1
