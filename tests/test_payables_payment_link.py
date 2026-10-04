"""End-to-end SQLite tests for immutable AP-to-cash payment evidence."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError, checksum_file
from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.payables_payment_link import payment_external_reference
from reconforge.infrastructure.sqlite_finance_posting import SQLiteFinancePostingRepository
from reconforge.infrastructure.sqlite_payables_payment_link import verify_sqlite_payment_link_storage
from reconforge.platform.common import PlatformError, ServerPrincipal, server_principal_context, trusted_local_mode
from reconforge.platform.finance_core import FinanceCoreService
from reconforge.platform.payables import PayablesService, PurchaseOrderLineInput, SupplierInvoiceLineInput
from reconforge.platform.payables_payment_link import PayablesPaymentLinkService
from tests.test_finance_core import _seed_finance_model

_PASSWORD = "Synthetic-payment-link-password-123"


def _principal(connection, username: str):
    auth = LocalAuthService(connection)
    user = auth.authenticate_user(username=username, password=_PASSWORD)
    assert user is not None
    return ServerPrincipal(user=user, permissions=frozenset(auth.roles.user_permissions(username)), step_up_active=True)


def _actor(connection, username: str):
    principal = _principal(connection, username)
    return trusted_local_mode(False), server_principal_context(principal), principal


def _setup_users(connection) -> None:
    auth = LocalAuthService(connection)
    auth.init_admin(username="maker", password=_PASSWORD)
    for username in ("checker", "poster", "settler"):
        auth.create_user(username=username, password=_PASSWORD, role="admin")


def _with_actor(connection, username: str):
    """Return a nested pair of context managers and its posting identity."""

    trusted, principal_context, principal = _actor(connection, username)
    return trusted, principal_context, PostingActor(
        principal.user.id,
        principal.user.username,
        principal.permissions,
        step_up_active=True,
    )


def _approved_invoice(connection) -> dict[str, object]:
    service = PayablesService(connection)
    trusted, principal_context, _ = _with_actor(connection, "maker")
    with trusted, principal_context:
        service.upsert_supplier(
            supplier_code="SUP-PAY",
            name="Synthetic Payment Supplier",
            currency_code="EGP",
            organization_code="SYN",
            entity_code="EG01",
            actor_label="maker",
        )
        order = service.create_purchase_order(
            po_number="PO-PAY",
            supplier_code="SUP-PAY",
            order_date="2026-07-01",
            currency_code="EGP",
            organization_code="SYN",
            entity_code="EG01",
            lines=[PurchaseOrderLineInput(item_code="ITEM-PAY", ordered_quantity="1", unit_price_minor=1_000)],
            actor_label="maker",
        )
        order = service.submit_purchase_order(str(order["id"]), expected_version=1, actor_label="maker")
    trusted, principal_context, _ = _with_actor(connection, "checker")
    with trusted, principal_context:
        order = service.approve_purchase_order(str(order["id"]), expected_version=2, actor_label="checker")
    trusted, principal_context, _ = _with_actor(connection, "maker")
    with trusted, principal_context:
        receipt = service.post_receipt(
            receipt_number="GR-PAY",
            purchase_order_id=str(order["id"]),
            receipt_date="2026-07-02",
            quantities={str(order["lines"][0]["id"]): "1"},
            actor_label="maker",
        )
        assert receipt["status"] == "Posted"
        invoice = service.create_supplier_invoice(
            invoice_number="INV-PAY",
            supplier_code="SUP-PAY",
            invoice_date="2026-07-03",
            currency_code="EGP",
            total_minor=1_000,
            organization_code="SYN",
            entity_code="EG01",
            purchase_order_id=str(order["id"]),
            lines=[
                SupplierInvoiceLineInput(
                    purchase_order_line_id=str(order["lines"][0]["id"]),
                    invoiced_quantity="1",
                    unit_price_minor=1_000,
                    line_total_minor=1_000,
                )
            ],
            actor_label="maker",
        )
        invoice = service.submit_supplier_invoice(str(invoice["id"]), expected_version=1, actor_label="maker")
        matched = service.run_three_way_match(str(invoice["id"]), actor_label="maker")
        assert matched.status == "Passed"
    trusted, principal_context, _ = _with_actor(connection, "checker")
    with trusted, principal_context:
        return service.approve_supplier_invoice(str(invoice["id"]), expected_version=3, actor_label="checker")


def _posted_payment_effect(
    connection,
    finance: FinanceCoreService,
    period: dict[str, object],
    invoice_id: str,
    amount_minor: int,
    number: str,
) -> dict[str, object]:
    amount = f"{amount_minor // 100}.{amount_minor % 100:02d}"
    trusted, principal_context, _ = _with_actor(connection, "maker")
    with trusted, principal_context:
        draft = finance.create_entry(
            entry_number=number,
            organization_code="SYN",
            entity_code="EG01",
            period_id=str(period["id"]),
            journal_code="GJ",
            posting_date="2026-07-05",
            description="Synthetic supplier settlement",
            external_reference=payment_external_reference(invoice_id),
            lines=[
                {"account_code": "2000", "debit": amount, "dimensions": {"CC": "HQ"}},
                {"account_code": "1010", "credit": amount, "dimensions": {"CC": "HQ"}},
            ],
            actor_label="maker",
        )
    trusted, principal_context, _ = _with_actor(connection, "checker")
    with trusted, principal_context:
        finance.validate_entry(str(draft["id"]), reason="Independent AP settlement review", actor_label="checker")
    trusted, principal_context, poster = _with_actor(connection, "poster")
    with trusted, principal_context:
        repository = SQLiteFinancePostingRepository(connection)
        preview = repository.preview(str(draft["id"]), actor=poster)
        return repository.post(
            str(draft["id"]),
            command_id=f"post-{number}",
            expected_validation_digest=str(preview["validation_digest"]),
            reason="Independent payment posting",
            actor=poster,
        )


def _fixture(tmp_path: Path, *, name: str = "payment-link.db"):
    path = tmp_path / name
    run_migrations(path)
    connection = connect(path, require_exists=True)
    _setup_users(connection)
    finance, period = _seed_finance_model(connection)
    finance.upsert_account(
        account_code="2000",
        name="Accounts payable",
        account_type="Liability",
        normal_balance="Credit",
    )
    invoice = _approved_invoice(connection)
    accounts = {
        str(row["account_code"]): str(row["id"])
        for row in connection.execute("SELECT id,account_code FROM accounts WHERE account_code IN ('1010','2000')")
    }
    return path, connection, finance, period, invoice, accounts


def _link(connection, invoice: dict[str, object], effect: dict[str, object], accounts: dict[str, str], *, command: str):
    trusted, principal_context, _ = _with_actor(connection, "settler")
    with trusted, principal_context:
        return PayablesPaymentLinkService(connection).link_finance_payment(
            str(invoice["id"]),
            finance_effect_id=str(effect["id"]),
            ap_account_id=accounts["2000"],
            cash_account_id=accounts["1010"],
            expected_invoice_version=int(invoice["row_version"]),
            command_id=command,
            actor_label="settler",
        )


def test_payment_link_sqlite_schema_serializes_each_invoice_version(tmp_path: Path) -> None:
    path = tmp_path / "payment-link-schema.db"
    run_migrations(path)
    connection = connect(path, require_exists=True)
    try:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ap_payment_links'"
        ).fetchone()
        assert row is not None
        assert "UNIQUE(supplier_invoice_id, invoice_version_before)" in str(row[0])
        assert "CHECK(amount_minor BETWEEN 1 AND 9000000000000000000)" in str(row[0])
    finally:
        connection.close()


def test_payment_links_consume_exact_reviewed_effects_and_replay_historically(tmp_path: Path) -> None:
    _path, connection, finance, period, invoice, accounts = _fixture(tmp_path)
    try:
        first_effect = _posted_payment_effect(connection, finance, period, str(invoice["id"]), 400, "JE-PAY-400")
        first = _link(connection, invoice, first_effect, accounts, command="settle-400")
        assert first["amount_minor"] == 400
        assert first["allocated_minor"] == 400
        assert first["outstanding_minor"] == 600
        assert first["invoice_status"] == "Approved"
        assert _link(connection, invoice, first_effect, accounts, command="settle-400") == first

        current = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
        second_effect = _posted_payment_effect(connection, finance, period, str(invoice["id"]), 600, "JE-PAY-600")
        second = _link(connection, current, second_effect, accounts, command="settle-600")
        assert second["allocated_minor"] == 1_000
        assert second["outstanding_minor"] == 0
        assert second["invoice_status"] == "Paid"
        # A lost acknowledgement for the first partial command must remain its
        # original receipt even after a later valid allocation settles the invoice.
        assert _link(connection, invoice, first_effect, accounts, command="settle-400") == first
        assert PayablesService(connection).get_supplier_invoice(str(invoice["id"]))["status"] == "Paid"
        trusted, principal_context, _ = _with_actor(connection, "settler")
        with trusted, principal_context:
            links = PayablesPaymentLinkService(connection).list_payment_links(str(invoice["id"]), actor_label="settler")
        assert [link["amount_minor"] for link in links] == [400, 600]
        assert connection.execute("SELECT count(*) FROM audit_events WHERE object_type='ap_payment_link'").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE event_type='ap.payment_linked'").fetchone()[0] == 2
        with pytest.raises(Exception, match="Paid status requires"):
            connection.execute("UPDATE ap_supplier_invoices SET status='Approved' WHERE id=?", (invoice["id"],))
        connection.rollback()
    finally:
        connection.close()


def test_payment_link_enforces_independent_invoice_settlement_and_exact_effect_shape(tmp_path: Path) -> None:
    _path, connection, finance, period, invoice, accounts = _fixture(tmp_path)
    try:
        effect = _posted_payment_effect(connection, finance, period, str(invoice["id"]), 1_000, "JE-PAY-SOD")
        trusted, principal_context, _ = _with_actor(connection, "maker")
        with trusted, principal_context, pytest.raises(PlatformError, match="cannot settle"):
            PayablesPaymentLinkService(connection).link_finance_payment(
                str(invoice["id"]),
                finance_effect_id=str(effect["id"]),
                ap_account_id=accounts["2000"],
                cash_account_id=accounts["1010"],
                expected_invoice_version=int(invoice["row_version"]),
                command_id="maker-cannot-settle",
                actor_label="maker",
            )
        # The rejected actor must not leave audit/outbox/link residue.
        assert connection.execute("SELECT count(*) FROM ap_payment_links").fetchone()[0] == 0
        result = _link(connection, invoice, effect, accounts, command="settle-approved")
        assert result["invoice_status"] == "Paid"
        link = dict(connection.execute("SELECT * FROM ap_payment_links").fetchone())
        with pytest.raises(Exception, match="immutable"):
            connection.execute("UPDATE ap_payment_links SET amount_minor=999 WHERE id=?", (link["id"],))
        connection.rollback()
        with pytest.raises(Exception, match="immutable exact settlement link"):
            connection.execute(
                """INSERT INTO ap_payment_link_commands
                   (workspace_id,command_id,settlement_actor_id,request_digest,result_json,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (link["workspace_id"], "forged", link["settlement_actor_id"], "0" * 64, "{}", "2026-07-05T00:00:00Z"),
            )
        connection.rollback()
    finally:
        connection.close()


def test_payment_link_translates_invalid_command_digest_to_controlled_error(tmp_path: Path) -> None:
    _path, connection, _finance, _period, invoice, accounts = _fixture(tmp_path)
    try:
        trusted, principal_context, _ = _with_actor(connection, "settler")
        with trusted, principal_context, pytest.raises(PlatformError, match="Expected invoice version must be a positive integer"):
            PayablesPaymentLinkService(connection).link_finance_payment(
                str(invoice["id"]),
                finance_effect_id="missing-effect",
                ap_account_id=accounts["2000"],
                cash_account_id=accounts["1010"],
                expected_invoice_version=0,
                command_id="invalid-version",
                actor_label="settler",
            )
        assert connection.execute("SELECT count(*) FROM ap_payment_links").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM ap_payment_link_commands").fetchone()[0] == 0
    finally:
        connection.close()


def test_payment_link_concurrent_full_allocations_admit_only_one(tmp_path: Path) -> None:
    path, connection, finance, period, invoice, accounts = _fixture(tmp_path)
    try:
        first = _posted_payment_effect(connection, finance, period, str(invoice["id"]), 600, "JE-PAY-RACE-A")
        second = _posted_payment_effect(connection, finance, period, str(invoice["id"]), 600, "JE-PAY-RACE-B")
    finally:
        connection.close()

    barrier = Barrier(2)

    def attempt(effect: dict[str, object], command: str) -> str:
        concurrent = connect(path, require_exists=True)
        try:
            barrier.wait(timeout=10)
            try:
                return str(
                    PayablesPaymentLinkService(concurrent).link_finance_payment(
                        str(invoice["id"]),
                        finance_effect_id=str(effect["id"]),
                        ap_account_id=accounts["2000"],
                        cash_account_id=accounts["1010"],
                        expected_invoice_version=int(invoice["row_version"]),
                        command_id=command,
                        actor_label="trusted-settler",
                    )["payment_link_id"]
                )
            except PlatformError as exc:
                return f"error:{exc}"
        finally:
            concurrent.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda values: attempt(*values), ((first, "race-a"), (second, "race-b"))))
    assert sum(not outcome.startswith("error:") for outcome in outcomes) == 1
    reopened = connect(path, require_exists=True)
    try:
        assert reopened.execute("SELECT count(*) FROM ap_payment_links").fetchone()[0] == 1
        assert PayablesService(reopened).get_supplier_invoice(str(invoice["id"]))["status"] == "Approved"
        assert reopened.execute("SELECT COALESCE(SUM(amount_minor),0) FROM ap_payment_links").fetchone()[0] == 600
    finally:
        reopened.close()


def test_payment_link_backup_restore_replays_exact_links_and_invoice_state(tmp_path: Path) -> None:
    path, connection, finance, period, invoice, accounts = _fixture(tmp_path, name="payment-link-backup-source.db")
    try:
        first_effect = _posted_payment_effect(connection, finance, period, str(invoice["id"]), 400, "JE-PAY-BACKUP-400")
        _link(connection, invoice, first_effect, accounts, command="backup-settle-400")
        current = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
        second_effect = _posted_payment_effect(connection, finance, period, str(invoice["id"]), 600, "JE-PAY-BACKUP-600")
        _link(connection, current, second_effect, accounts, command="backup-settle-600")
        verify_sqlite_payment_link_storage(connection)
        original_links = [
            dict(row)
            for row in connection.execute(
                "SELECT id,finance_effect_id,amount_minor,invoice_version_before FROM ap_payment_links "
                "ORDER BY invoice_version_before"
            ).fetchall()
        ]
    finally:
        connection.close()

    backup = create_backup(path, tmp_path / "payment-link-backup")
    restored_path = tmp_path / "payment-link-restored.db"
    restore_backup(restored_path, backup.backup_path)

    restored = connect(restored_path, require_exists=True)
    try:
        verify_sqlite_payment_link_storage(restored)
        restored_links = [
            dict(row)
            for row in restored.execute(
                "SELECT id,finance_effect_id,amount_minor,invoice_version_before FROM ap_payment_links "
                "ORDER BY invoice_version_before"
            ).fetchall()
        ]
        restored_invoice = PayablesService(restored).get_supplier_invoice(str(invoice["id"]))
        assert restored_links == original_links
        assert restored_invoice["status"] == "Paid"
        assert restored.execute("SELECT COUNT(*) FROM ap_payment_link_commands").fetchone()[0] == 2
    finally:
        restored.close()


def test_payment_link_backup_refuses_tampered_outbox_evidence(tmp_path: Path) -> None:
    path, connection, finance, period, invoice, accounts = _fixture(tmp_path, name="payment-link-tamper-source.db")
    try:
        effect = _posted_payment_effect(connection, finance, period, str(invoice["id"]), 1_000, "JE-PAY-TAMPER")
        _link(connection, invoice, effect, accounts, command="tamper-settle")
        link = connection.execute("SELECT outbox_event_id FROM ap_payment_links").fetchone()
        assert link is not None
    finally:
        connection.close()

    backup = create_backup(path, tmp_path / "payment-link-tamper-backup")
    payload = json.loads(backup.backup_path.read_text(encoding="utf-8"))
    for event in payload["tables"]["outbox_events"]:
        if event["id"] == link["outbox_event_id"]:
            event["payload_json"] = "{}"
    backup.backup_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    manifest = json.loads(backup.manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["backup.json"]["sha256"] = checksum_file(backup.backup_path)
    manifest["artifacts"]["backup.json"]["bytes"] = backup.backup_path.stat().st_size
    backup.manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    with pytest.raises(DBBridgeError, match="Unable to restore local DB backup"):
        restore_backup(tmp_path / "payment-link-tamper-restored.db", backup.backup_path)


def test_payment_link_api_exposes_only_retained_evidence_to_authorized_settler(tmp_path: Path) -> None:
    path, connection, finance, period, invoice, accounts = _fixture(tmp_path, name="payment-link-api.db")
    try:
        effect = _posted_payment_effect(connection, finance, period, str(invoice["id"]), 1_000, "JE-PAY-API")
    finally:
        connection.close()

    client = TestClient(create_api_app(path))
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "settler", "password": _PASSWORD},
    )
    assert login.status_code == 200
    invoice_id = str(invoice["id"])
    effect_id = str(effect["id"])
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.post(
        f"/api/v1/payables/invoices/{invoice_id}/payment-links",
        headers=headers,
        json={
            "finance_effect_id": effect_id,
            "ap_account_id": accounts["2000"],
            "cash_account_id": accounts["1010"],
            "expected_invoice_version": invoice["row_version"],
            "command_id": "api-settlement",
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["amount_minor"] == 1_000
    assert created["invoice_status"] == "Paid"
    assert "snapshot_json" not in created
    listed = client.get(
        f"/api/v1/payables/invoices/{invoice_id}/payment-links",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert [item["finance_effect_id"] for item in listed.json()["payment_links"]] == [effect_id]
