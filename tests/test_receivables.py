from __future__ import annotations

from pathlib import Path

import pytest

import reconforge.platform.common as common_module
from reconforge.audit import AuditLedgerError
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.platform.common import PlatformError
from reconforge.platform.receivables import (
    ReceiptAllocationInput,
    ReceivableInvoiceLineInput,
    ReceivablesService,
)


def _service(tmp_path: Path):
    db_path = tmp_path / "receivables.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    auth = LocalAuthService(connection)
    auth.init_admin(username="admin", password="Secret-123")
    auth.create_user(username="prep", password="Secret-123", role="preparer")
    auth.create_user(username="review", password="Secret-123", role="reviewer")
    auth.create_user(username="controller", password="Secret-123", role="controller")
    return connection, ReceivablesService(connection)


def _invoice(service: ReceivablesService, *, number: str = "AR-001", total: int = 3_000) -> dict[str, object]:
    service.upsert_customer(
        customer_code="CUS-001",
        name="Synthetic Customer",
        currency_code="USD",
        credit_limit_minor=10_000,
        actor_label="prep",
    )
    return service.create_invoice(
        invoice_number=number,
        customer_code="CUS-001",
        invoice_date="2026-07-01",
        currency_code="USD",
        tax_minor=0,
        lines=[
            ReceivableInvoiceLineInput(
                description="Synthetic service",
                quantity="2",
                unit_price_minor=total // 2,
                line_total_minor=total,
            ),
        ],
        actor_label="prep",
    )


def test_receivables_credit_control_receipt_allocation_and_aging(tmp_path: Path) -> None:
    connection, service = _service(tmp_path)
    try:
        invoice = _invoice(service)
        repeated = service.create_invoice(
            invoice_number="AR-IDEMPOTENT",
            customer_code="CUS-001",
            invoice_date="2026-07-01",
            currency_code="USD",
            tax_minor=0,
            lines=[
                ReceivableInvoiceLineInput(
                    description="Recurring", quantity="1", unit_price_minor=100, line_total_minor=100
                )
            ],
            idempotency_key="invoice-1",
            actor_label="prep",
        )
        assert (
            service.create_invoice(
                invoice_number="AR-IDEMPOTENT",
                customer_code="CUS-001",
                invoice_date="2026-07-01",
                currency_code="USD",
                tax_minor=0,
                lines=[
                    ReceivableInvoiceLineInput(
                        description="Recurring", quantity="1", unit_price_minor=100, line_total_minor=100
                    )
                ],
                idempotency_key="invoice-1",
                actor_label="prep",
            )["id"]
            == repeated["id"]
        )
        invoice = service.submit_invoice(str(invoice["id"]), expected_version=1, actor_label="prep")
        invoice = service.approve_invoice(str(invoice["id"]), expected_version=2, actor_label="review")
        assert invoice["status"] == "Approved"

        receipt = service.post_receipt(
            receipt_number="RCPT-001",
            customer_code="CUS-001",
            receipt_date="2026-07-15",
            currency_code="USD",
            amount_minor=3_000,
            allocations=[ReceiptAllocationInput(invoice_id=str(invoice["id"]), amount_minor=1_000)],
            actor_label="prep",
        )
        assert receipt["allocated_minor"] == 1_000
        assert receipt["unallocated_minor"] == 2_000
        assert service.get_invoice(str(invoice["id"]))["status"] == "PartiallyPaid"
        receipt = service.allocate_receipt(
            str(receipt["id"]),
            invoice_id=str(invoice["id"]),
            amount_minor=2_000,
            expected_version=int(receipt["row_version"]),
            actor_label="prep",
        )
        assert receipt["unallocated_minor"] == 0
        assert service.get_invoice(str(invoice["id"]))["status"] == "Paid"
        aging_invoice = service.create_invoice(
            invoice_number="AR-AGING",
            customer_code="CUS-001",
            invoice_date="2026-07-01",
            currency_code="USD",
            tax_minor=0,
            lines=[
                ReceivableInvoiceLineInput(
                    description="Aging item", quantity="1", unit_price_minor=500, line_total_minor=500
                )
            ],
            actor_label="prep",
        )
        aging_invoice = service.submit_invoice(str(aging_invoice["id"]), expected_version=1, actor_label="prep")
        service.approve_invoice(str(aging_invoice["id"]), expected_version=2, actor_label="review")
        aging = service.aging_report(workspace="default", as_of_date="2026-08-31")
        assert aging["total_outstanding_minor"] == 500
        assert aging["items"][0]["bucket"] == "61-90"
        assert connection.execute("SELECT COUNT(*) AS count FROM ar_receipt_allocations").fetchone()["count"] == 1
        assert (
            connection.execute("SELECT COUNT(*) AS count FROM audit_events WHERE object_type LIKE 'ar_%'").fetchone()[
                "count"
            ]
            >= 5
        )
        assert (
            connection.execute("SELECT COUNT(*) AS count FROM outbox_events WHERE event_type LIKE 'ar.%'").fetchone()[
                "count"
            ]
            >= 5
        )
    finally:
        connection.close()


def test_receivables_credit_hold_and_limit_require_audited_override(tmp_path: Path) -> None:
    connection, service = _service(tmp_path)
    try:
        service.upsert_customer(
            customer_code="CUS-HOLD",
            name="Held Customer",
            currency_code="USD",
            credit_limit_minor=1_000,
            credit_hold=True,
            actor_label="prep",
        )
        invoice = service.create_invoice(
            invoice_number="AR-HOLD",
            customer_code="CUS-HOLD",
            invoice_date="2026-07-01",
            currency_code="USD",
            tax_minor=0,
            lines=[
                ReceivableInvoiceLineInput(
                    description="Held sale", quantity="1", unit_price_minor=1_500, line_total_minor=1_500
                )
            ],
            actor_label="prep",
        )
        invoice = service.submit_invoice(str(invoice["id"]), expected_version=1, actor_label="prep")
        with pytest.raises(PlatformError, match="Credit control blocked"):
            service.approve_invoice(str(invoice["id"]), expected_version=2, actor_label="review")
        with pytest.raises(PlatformError, match="Permission denied"):
            service.approve_invoice(
                str(invoice["id"]),
                expected_version=2,
                credit_override_reason="controller approved held-account exception",
                actor_label="review",
            )
        approved = service.approve_invoice(
            str(invoice["id"]),
            expected_version=2,
            credit_override_reason="controller approved held-account exception",
            actor_label="controller",
        )
        assert approved["status"] == "Approved"
        assert approved["credit_override_reason"] == "controller approved held-account exception"
    finally:
        connection.close()


def test_invoice_creator_cannot_self_approve_even_with_credit_override(tmp_path: Path) -> None:
    connection, service = _service(tmp_path)
    try:
        service.upsert_customer(
            customer_code="CUS-SELF",
            name="Self approval customer",
            currency_code="USD",
            credit_limit_minor=10_000,
            actor_label="controller",
        )
        invoice = service.create_invoice(
            invoice_number="AR-SELF",
            customer_code="CUS-SELF",
            invoice_date="2026-07-01",
            currency_code="USD",
            tax_minor=0,
            lines=[
                ReceivableInvoiceLineInput(
                    description="Self approval boundary",
                    quantity="1",
                    unit_price_minor=100,
                    line_total_minor=100,
                )
            ],
            actor_label="controller",
        )
        submitted = service.submit_invoice(str(invoice["id"]), expected_version=1, actor_label="controller")

        with pytest.raises(PlatformError, match="creator cannot approve"):
            service.approve_invoice(
                str(submitted["id"]),
                expected_version=2,
                credit_override_reason="emergency",
                actor_label="controller",
            )

        assert service.get_invoice(str(invoice["id"]))["status"] == "Submitted"
    finally:
        connection.close()


def test_receivables_reject_invalid_amount_and_roll_back_audit_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, service = _service(tmp_path)
    try:
        with pytest.raises(PlatformError, match="total"):
            service.upsert_customer(
                customer_code="CUS-BAD",
                name="Bad Customer",
                currency_code="USD",
                credit_limit_minor=1_000,
                actor_label="prep",
            )
            service.create_invoice(
                invoice_number="AR-BAD",
                customer_code="CUS-BAD",
                invoice_date="2026-07-01",
                currency_code="USD",
                tax_minor=0,
                lines=[
                    ReceivableInvoiceLineInput(
                        description="Bad", quantity="2", unit_price_minor=100, line_total_minor=99
                    )
                ],
                actor_label="prep",
            )

        before_audit_count = connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]
        monkeypatch.setattr(
            common_module, "audit", lambda *_args, **_kwargs: (_ for _ in ()).throw(AuditLedgerError("forced"))
        )
        with pytest.raises(PlatformError, match="audit evidence"):
            service.upsert_customer(
                customer_code="CUS-ROLLBACK",
                name="Rollback Customer",
                currency_code="USD",
                credit_limit_minor=1_000,
                actor_label="prep",
            )
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM ar_customers WHERE customer_code = 'CUS-ROLLBACK'"
            ).fetchone()["count"]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == before_audit_count
        )
    finally:
        connection.close()


def test_receivables_backup_restore_and_migration_upgrade(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    run_migrations(source, target_version=19)
    assert run_migrations(source).current_version == 20
    connection = connect(source, require_exists=True)
    try:
        service = ReceivablesService(connection)
        invoice = _invoice(service, number="AR-BACKUP", total=500)
        invoice = service.submit_invoice(str(invoice["id"]), expected_version=1)
        service.approve_invoice(str(invoice["id"]), expected_version=2)
    finally:
        connection.close()
    backup = create_backup(source, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)
    connection = connect(restored, require_exists=True)
    try:
        assert connection.execute("SELECT COUNT(*) AS count FROM ar_customers").fetchone()["count"] == 1
        assert (
            connection.execute("SELECT COUNT(*) AS count FROM ar_invoices WHERE status = 'Approved'").fetchone()[
                "count"
            ]
            == 1
        )
        assert connection.execute("SELECT COUNT(*) AS count FROM ar_idempotency_keys").fetchone()["count"] == 0
    finally:
        connection.close()
