"""SQLite integration tests for Finance-evidenced AP allocation reversal."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect
from reconforge.db.backup import create_backup, restore_backup
from reconforge.infrastructure.sqlite_finance_posting import SQLiteFinancePostingRepository
from reconforge.infrastructure.sqlite_payables_payment_link import verify_sqlite_payment_link_storage
from reconforge.platform.common import PlatformError
from reconforge.platform.payables import PayablesService
from reconforge.platform.payables_payment_link import PayablesPaymentLinkService
from tests.test_payables_payment_link import (
    _PASSWORD,
    _fixture,
    _link,
    _posted_payment_effect,
    _with_actor,
)


def _reversal_effect(
    connection,
    *,
    original_effect_id: str,
    period_id: str,
    number: str,
) -> dict[str, object]:
    """Use the Finance Posting reversal aggregate; AP never builds this entry."""

    repository = SQLiteFinancePostingRepository(connection)
    trusted, principal_context, maker = _with_actor(connection, "maker")
    with trusted, principal_context:
        draft = repository.prepare_reversal(
            original_effect_id,
            command_id=f"prepare-{number}",
            entry_number=number,
            period_id=period_id,
            posting_date="2026-07-06",
            reason="Synthetic independently governed payment correction",
            actor=maker,
        )
    from reconforge.platform.finance_core import FinanceCoreService

    trusted, principal_context, _ = _with_actor(connection, "checker")
    with trusted, principal_context:
        FinanceCoreService(connection).validate_entry(
            str(draft["entry_id"]),
            reason="Independent reversal review",
            actor_label="checker",
        )
    trusted, principal_context, poster = _with_actor(connection, "poster")
    with trusted, principal_context:
        preview = repository.preview(str(draft["entry_id"]), actor=poster)
        return repository.post(
            str(draft["entry_id"]),
            command_id=f"post-{number}",
            expected_validation_digest=str(preview["validation_digest"]),
            reason="Independent reversal posting",
            actor=poster,
        )


def _add_reverser(connection) -> None:
    LocalAuthService(connection).create_user(
        username="reverser", password=_PASSWORD, role="admin"
    )


def _reverse(
    connection,
    *,
    invoice_id: str,
    payment_link_id: str,
    reversal_effect_id: str,
    expected_invoice_version: int,
    command: str,
) -> dict[str, object]:
    trusted, principal_context, _ = _with_actor(connection, "reverser")
    with trusted, principal_context:
        return PayablesPaymentLinkService(connection).reverse_finance_payment_link(
            invoice_id,
            payment_link_id,
            reversal_finance_effect_id=reversal_effect_id,
            expected_invoice_version=expected_invoice_version,
            command_id=command,
            actor_label="reverser",
        )


def test_payment_link_reversal_uses_posted_full_inverse_and_replays_historically(
    tmp_path: Path,
) -> None:
    _path, connection, finance, period, invoice, accounts = _fixture(tmp_path)
    try:
        _add_reverser(connection)
        original = _posted_payment_effect(
            connection, finance, period, str(invoice["id"]), 1_000, "JE-REV-ORIGINAL"
        )
        linked = _link(connection, invoice, original, accounts, command="settle-reversal-source")
        assert linked["invoice_status"] == "Paid"
        inverse = _reversal_effect(
            connection,
            original_effect_id=str(original["id"]),
            period_id=str(period["id"]),
            number="JE-REV-INVERSE",
        )
        current = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
        reversed_result = _reverse(
            connection,
            invoice_id=str(invoice["id"]),
            payment_link_id=str(linked["payment_link_id"]),
            reversal_effect_id=str(inverse["id"]),
            expected_invoice_version=int(current["row_version"]),
            command="reverse-payment-link",
        )
        assert reversed_result["original_finance_effect_id"] == original["id"]
        assert reversed_result["reversal_finance_effect_id"] == inverse["id"]
        assert reversed_result["allocated_minor"] == 0
        assert reversed_result["invoice_status"] == "Approved"
        assert _reverse(
            connection,
            invoice_id=str(invoice["id"]),
            payment_link_id=str(linked["payment_link_id"]),
            reversal_effect_id=str(inverse["id"]),
            expected_invoice_version=int(current["row_version"]),
            command="reverse-payment-link",
        ) == reversed_result
        invoice_after = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
        replacement = _posted_payment_effect(
            connection, finance, period, str(invoice["id"]), 1_000, "JE-REV-REPLACEMENT"
        )
        replacement_result = _link(
            connection, invoice_after, replacement, accounts, command="settle-after-reversal"
        )
        assert replacement_result["invoice_status"] == "Paid"
        # A retry remains the response frozen at the reversal transition,
        # rather than today’s balance after a later settlement.
        assert _reverse(
            connection,
            invoice_id=str(invoice["id"]),
            payment_link_id=str(linked["payment_link_id"]),
            reversal_effect_id=str(inverse["id"]),
            expected_invoice_version=int(current["row_version"]),
            command="reverse-payment-link",
        ) == reversed_result
        verify_sqlite_payment_link_storage(connection)
        assert connection.execute("SELECT COUNT(*) FROM ap_payment_link_reversals").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM ap_payment_link_reversal_commands").fetchone()[0] == 1
        with pytest.raises(Exception, match="cannot be deleted"):
            connection.execute("DELETE FROM ap_payment_link_reversals")
        connection.rollback()
    finally:
        connection.close()


def test_payment_link_reversal_refuses_non_reversal_and_duty_collisions(tmp_path: Path) -> None:
    _path, connection, finance, period, invoice, accounts = _fixture(tmp_path)
    try:
        _add_reverser(connection)
        original = _posted_payment_effect(
            connection, finance, period, str(invoice["id"]), 1_000, "JE-REV-DENY"
        )
        linked = _link(connection, invoice, original, accounts, command="settle-reversal-deny")
        current = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
        with pytest.raises(PlatformError, match="requires the posted Finance reversal"):
            _reverse(
                connection,
                invoice_id=str(invoice["id"]),
                payment_link_id=str(linked["payment_link_id"]),
                reversal_effect_id=str(original["id"]),
                expected_invoice_version=int(current["row_version"]),
                command="not-an-inverse",
            )
        inverse = _reversal_effect(
            connection,
            original_effect_id=str(original["id"]),
            period_id=str(period["id"]),
            number="JE-REV-DENY-INVERSE",
        )
        trusted, principal_context, _ = _with_actor(connection, "maker")
        with trusted, principal_context, pytest.raises(PlatformError, match="cannot reverse"):
            PayablesPaymentLinkService(connection).reverse_finance_payment_link(
                str(invoice["id"]),
                str(linked["payment_link_id"]),
                reversal_finance_effect_id=str(inverse["id"]),
                expected_invoice_version=int(current["row_version"]),
                command_id="maker-cannot-reverse",
                actor_label="maker",
            )
        assert connection.execute("SELECT COUNT(*) FROM ap_payment_link_reversals").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM ap_payment_link_reversal_commands").fetchone()[0] == 0
    finally:
        connection.close()


def test_payment_link_reversal_concurrent_commands_admit_one_effect(tmp_path: Path) -> None:
    path, connection, finance, period, invoice, accounts = _fixture(tmp_path)
    try:
        _add_reverser(connection)
        original = _posted_payment_effect(
            connection, finance, period, str(invoice["id"]), 1_000, "JE-REV-RACE"
        )
        linked = _link(connection, invoice, original, accounts, command="settle-reversal-race")
        inverse = _reversal_effect(
            connection,
            original_effect_id=str(original["id"]),
            period_id=str(period["id"]),
            number="JE-REV-RACE-INVERSE",
        )
        current = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
    finally:
        connection.close()

    barrier = Barrier(2)

    def attempt(command: str) -> str:
        concurrent = connect(path, require_exists=True)
        try:
            barrier.wait(timeout=10)
            try:
                return str(
                    PayablesPaymentLinkService(concurrent).reverse_finance_payment_link(
                        str(invoice["id"]),
                        str(linked["payment_link_id"]),
                        reversal_finance_effect_id=str(inverse["id"]),
                        expected_invoice_version=int(current["row_version"]),
                        command_id=command,
                        actor_label="trusted-reverser",
                    )["payment_link_reversal_id"]
                )
            except PlatformError as exc:
                return f"error:{exc}"
        finally:
            concurrent.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, ("reverse-race-a", "reverse-race-b")))
    assert sum(not outcome.startswith("error:") for outcome in outcomes) == 1
    reopened = connect(path, require_exists=True)
    try:
        assert reopened.execute("SELECT COUNT(*) FROM ap_payment_link_reversals").fetchone()[0] == 1
        assert PayablesService(reopened).get_supplier_invoice(str(invoice["id"]))["status"] == "Approved"
    finally:
        reopened.close()


def test_payment_link_reversal_backup_restore_replays_retained_evidence(tmp_path: Path) -> None:
    path, connection, finance, period, invoice, accounts = _fixture(tmp_path, name="reversal-source.db")
    try:
        _add_reverser(connection)
        original = _posted_payment_effect(
            connection, finance, period, str(invoice["id"]), 400, "JE-REV-BACKUP-400"
        )
        linked = _link(connection, invoice, original, accounts, command="settle-reversal-backup-400")
        second_effect = _posted_payment_effect(
            connection, finance, period, str(invoice["id"]), 600, "JE-REV-BACKUP-600"
        )
        after_first = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
        assert _link(
            connection,
            after_first,
            second_effect,
            accounts,
            command="settle-reversal-backup-600",
        )["invoice_status"] == "Paid"
        inverse = _reversal_effect(
            connection,
            original_effect_id=str(original["id"]),
            period_id=str(period["id"]),
            number="JE-REV-BACKUP-INVERSE",
        )
        current = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
        reversed_result = _reverse(
            connection,
            invoice_id=str(invoice["id"]),
            payment_link_id=str(linked["payment_link_id"]),
            reversal_effect_id=str(inverse["id"]),
            expected_invoice_version=int(current["row_version"]),
            command="reverse-backup",
        )
        assert reversed_result["allocated_minor"] == 600
        assert reversed_result["invoice_status"] == "Approved"
        replacement_effect = _posted_payment_effect(
            connection, finance, period, str(invoice["id"]), 400, "JE-REV-BACKUP-REPLACEMENT"
        )
        after_reversal = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
        assert _link(
            connection,
            after_reversal,
            replacement_effect,
            accounts,
            command="settle-reversal-backup-replacement",
        )["invoice_status"] == "Paid"
        verify_sqlite_payment_link_storage(connection)
    finally:
        connection.close()

    backup = create_backup(path, tmp_path / "reversal-backup")
    restored_path = tmp_path / "reversal-restored.db"
    restore_backup(restored_path, backup.backup_path)
    restored = connect(restored_path, require_exists=True)
    try:
        verify_sqlite_payment_link_storage(restored)
        restored_reversal = dict(restored.execute("SELECT * FROM ap_payment_link_reversals").fetchone())
        assert restored_reversal["id"] == reversed_result["payment_link_reversal_id"]
        assert PayablesService(restored).get_supplier_invoice(str(invoice["id"]))["status"] == "Paid"
        assert restored.execute("SELECT COUNT(*) FROM ap_payment_links").fetchone()[0] == 3
        assert _reverse(
            restored,
            invoice_id=str(invoice["id"]),
            payment_link_id=str(linked["payment_link_id"]),
            reversal_effect_id=str(inverse["id"]),
            expected_invoice_version=int(current["row_version"]),
            command="reverse-backup",
        ) == reversed_result
    finally:
        restored.close()


def test_payment_link_reversal_api_requires_reverse_permission_and_projects_evidence(
    tmp_path: Path,
) -> None:
    path, connection, finance, period, invoice, accounts = _fixture(tmp_path, name="reversal-api.db")
    try:
        _add_reverser(connection)
        LocalAuthService(connection).create_user(
            username="reversal-reader", password=_PASSWORD, role="reviewer"
        )
        original = _posted_payment_effect(
            connection, finance, period, str(invoice["id"]), 1_000, "JE-REV-API-ORIGINAL"
        )
        linked = _link(connection, invoice, original, accounts, command="settle-reversal-api")
        inverse = _reversal_effect(
            connection,
            original_effect_id=str(original["id"]),
            period_id=str(period["id"]),
            number="JE-REV-API-INVERSE",
        )
        current = PayablesService(connection).get_supplier_invoice(str(invoice["id"]))
    finally:
        connection.close()

    client = TestClient(create_api_app(path))

    def headers(username: str) -> dict[str, str]:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": _PASSWORD},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    invoice_id = str(invoice["id"])
    reversal_path = (
        f"/api/v1/payables/invoices/{invoice_id}/payment-links/{linked['payment_link_id']}/reversal"
    )
    payload = {
        "reversal_finance_effect_id": str(inverse["id"]),
        "expected_invoice_version": int(current["row_version"]),
        "command_id": "reverse-payment-link-api",
    }
    denied = client.post(reversal_path, headers=headers("reversal-reader"), json=payload)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "permission_denied"

    reverser_headers = headers("reverser")
    created = client.post(reversal_path, headers=reverser_headers, json=payload)
    assert created.status_code == 200, created.text
    result = created.json()
    assert result["payment_link_id"] == linked["payment_link_id"]
    assert result["reversal_finance_effect_id"] == inverse["id"]
    assert result["allocated_minor"] == 0
    assert result["invoice_status"] == "Approved"
    assert {"snapshot_json", "request_digest", "command_id"}.isdisjoint(result)
    assert client.post(reversal_path, headers=reverser_headers, json=payload).json() == result

    listed = client.get(
        f"/api/v1/payables/invoices/{invoice_id}/payment-link-reversals",
        headers=reverser_headers,
    )
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()["payment_link_reversals"]] == [
        result["payment_link_reversal_id"]
    ]
