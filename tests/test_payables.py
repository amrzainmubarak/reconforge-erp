from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest

import reconforge.platform.common as common_module
from reconforge.audit import AuditLedgerError
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.platform.common import PlatformError
from reconforge.platform.payables import (
    PayablesService,
    PurchaseOrderLineInput,
    SupplierInvoiceLineInput,
)

payables_module = import_module("reconforge.infrastructure.sqlite_payables")


def _fail_audit(*_args: object, **_kwargs: object) -> None:
    raise AuditLedgerError("forced audit failure")


def _fail_outbox(*_args: object, **_kwargs: object) -> None:
    raise PlatformError("forced outbox failure")


def _service(tmp_path: Path):
    db_path = tmp_path / "payables.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    return connection, PayablesService(connection)


def _prepare_purchase_order(service: PayablesService) -> dict[str, object]:
    service.upsert_supplier(supplier_code="SUP-001", name="Synthetic Supplier", currency_code="USD")
    return service.create_purchase_order(
        po_number="PO-001",
        supplier_code="SUP-001",
        order_date="2026-07-01",
        currency_code="USD",
        lines=[PurchaseOrderLineInput(item_code="ITEM-001", ordered_quantity="3", unit_price_minor=1_000)],
        idempotency_key="po-create-1",
    )


def test_payables_three_way_match_passes_and_is_idempotent(tmp_path: Path) -> None:
    connection, service = _service(tmp_path)
    try:
        order = _prepare_purchase_order(service)
        repeated = _prepare_purchase_order(service)
        assert repeated["id"] == order["id"]
        assert connection.execute("SELECT COUNT(*) AS count FROM ap_purchase_orders").fetchone()["count"] == 1

        order = service.submit_purchase_order(str(order["id"]), expected_version=1)
        order = service.approve_purchase_order(str(order["id"]), expected_version=2, actor_label="independent-approver")
        line_id = str(order["lines"][0]["id"])
        receipt = service.post_receipt(
            receipt_number="GR-001",
            purchase_order_id=str(order["id"]),
            receipt_date="2026-07-03",
            quantities={line_id: "3"},
            idempotency_key="receipt-1",
        )
        assert receipt["status"] == "Posted"
        invoice = service.create_supplier_invoice(
            invoice_number="INV-001",
            supplier_code="SUP-001",
            invoice_date="2026-07-04",
            currency_code="USD",
            total_minor=3_000,
            purchase_order_id=str(order["id"]),
            lines=[
                SupplierInvoiceLineInput(
                    purchase_order_line_id=line_id,
                    invoiced_quantity="3",
                    unit_price_minor=1_000,
                    line_total_minor=3_000,
                ),
            ],
        )
        invoice = service.submit_supplier_invoice(str(invoice["id"]), expected_version=1)
        match = service.run_three_way_match(str(invoice["id"]))
        assert match.status == "Passed"
        assert match.quantity_variance == "0"
        assert match.price_variance_minor == 0
        assert match.total_variance_minor == 0
        invoice = service.approve_supplier_invoice(
            str(invoice["id"]), expected_version=3, actor_label="independent-approver"
        )
        assert invoice["status"] == "Approved"
        assert connection.execute("SELECT COUNT(*) AS count FROM exceptions_queue").fetchone()["count"] == 0
        event_types = {
            str(row["event_type"]) for row in connection.execute("SELECT event_type FROM outbox_events").fetchall()
        }
        assert "ap.purchase_order.created" in event_types
        assert "ap.goods_receipt.posted" in event_types
        assert "ap.three_way_match.completed" in event_types
    finally:
        connection.close()


def test_payables_three_way_exception_is_visible_and_resolves(tmp_path: Path) -> None:
    connection, service = _service(tmp_path)
    try:
        order = _prepare_purchase_order(service)
        order = service.submit_purchase_order(str(order["id"]), expected_version=1)
        order = service.approve_purchase_order(str(order["id"]), expected_version=2, actor_label="independent-approver")
        line_id = str(order["lines"][0]["id"])
        service.post_receipt(
            receipt_number="GR-002",
            purchase_order_id=str(order["id"]),
            receipt_date="2026-07-03",
            quantities={line_id: "2"},
        )
        invoice = service.create_supplier_invoice(
            invoice_number="INV-002",
            supplier_code="SUP-001",
            invoice_date="2026-07-04",
            currency_code="USD",
            total_minor=3_300,
            purchase_order_id=str(order["id"]),
            lines=[
                SupplierInvoiceLineInput(
                    purchase_order_line_id=line_id,
                    invoiced_quantity="3",
                    unit_price_minor=1_100,
                    line_total_minor=3_300,
                ),
            ],
        )
        invoice = service.submit_supplier_invoice(str(invoice["id"]), expected_version=1)
        match = service.run_three_way_match(str(invoice["id"]))
        assert match.status == "Exception"
        assert "AP-3WM-PRICE" in match.reason
        exception = connection.execute(
            "SELECT * FROM exceptions_queue WHERE source_type = 'ap_three_way_match' AND source_id = ?",
            (match.match_id,),
        ).fetchone()
        assert exception is not None
        assert exception["status"] == "Open"
        assert service.get_supplier_invoice(str(invoice["id"]))["status"] == "Exception"
    finally:
        connection.close()


def test_payables_rejects_stale_versions_and_invalid_values(tmp_path: Path) -> None:
    connection, service = _service(tmp_path)
    try:
        service.upsert_supplier(supplier_code="SUP-001", name="Synthetic Supplier", currency_code="USD")
        with pytest.raises(PlatformError, match="quantity"):
            service.create_purchase_order(
                po_number="PO-BAD",
                supplier_code="SUP-001",
                order_date="2026-07-01",
                currency_code="USD",
                lines=[PurchaseOrderLineInput(item_code="ITEM-001", ordered_quantity="0", unit_price_minor=1_000)],
            )
        order = service.create_purchase_order(
            po_number="PO-002",
            supplier_code="SUP-001",
            order_date="2026-07-01",
            currency_code="USD",
            lines=[PurchaseOrderLineInput(item_code="ITEM-001", ordered_quantity="1", unit_price_minor=1_000)],
        )
        with pytest.raises(PlatformError, match="concurrently"):
            service.submit_purchase_order(str(order["id"]), expected_version=2)
        assert service.get_purchase_order(str(order["id"]))["status"] == "Draft"
    finally:
        connection.close()


def test_purchase_order_creator_cannot_self_approve_in_trusted_local_mode(tmp_path: Path) -> None:
    connection, service = _service(tmp_path)
    try:
        order = _prepare_purchase_order(service)
        submitted = service.submit_purchase_order(str(order["id"]), expected_version=1)

        with pytest.raises(PlatformError, match="creator cannot approve"):
            service.approve_purchase_order(str(submitted["id"]), expected_version=2)

        assert service.get_purchase_order(str(order["id"]))["status"] == "Submitted"
    finally:
        connection.close()


def test_payables_rolls_back_when_audit_append_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connection, service = _service(tmp_path)
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            service.upsert_supplier(supplier_code="SUP-FAIL", name="Synthetic Supplier", currency_code="USD")
        assert connection.execute("SELECT COUNT(*) AS count FROM ap_suppliers").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == 0
    finally:
        connection.close()


def test_payables_rolls_back_when_outbox_append_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connection, service = _service(tmp_path)
    monkeypatch.setattr(payables_module, "append_outbox_event", _fail_outbox)
    try:
        with pytest.raises(PlatformError, match="outbox"):
            service.upsert_supplier(supplier_code="SUP-OUTBOX", name="Synthetic Supplier", currency_code="USD")
        assert connection.execute("SELECT COUNT(*) AS count FROM ap_suppliers").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == 0
    finally:
        connection.close()


def test_payables_backup_restore_preserves_three_way_match_data(tmp_path: Path) -> None:
    source_db = tmp_path / "payables-source.db"
    run_migrations(source_db)
    connection = connect(source_db, require_exists=True)
    try:
        service = PayablesService(connection)
        order = _prepare_purchase_order(service)
        order = service.submit_purchase_order(str(order["id"]), expected_version=1)
        order = service.approve_purchase_order(str(order["id"]), expected_version=2, actor_label="independent-approver")
        line_id = str(order["lines"][0]["id"])
        service.post_receipt(
            receipt_number="GR-BACKUP",
            purchase_order_id=str(order["id"]),
            receipt_date="2026-07-03",
            quantities={line_id: "3"},
            idempotency_key="receipt-backup",
        )
        invoice = service.create_supplier_invoice(
            invoice_number="INV-BACKUP",
            supplier_code="SUP-001",
            invoice_date="2026-07-04",
            currency_code="USD",
            total_minor=3_000,
            purchase_order_id=str(order["id"]),
            lines=[
                SupplierInvoiceLineInput(
                    purchase_order_line_id=line_id,
                    invoiced_quantity="3",
                    unit_price_minor=1_000,
                    line_total_minor=3_000,
                ),
            ],
        )
        invoice = service.submit_supplier_invoice(str(invoice["id"]), expected_version=1)
        match = service.run_three_way_match(str(invoice["id"]))
        assert match.status == "Passed"
    finally:
        connection.close()

    backup = create_backup(source_db, tmp_path / "payables-backup")
    restored_db = tmp_path / "payables-restored.db"
    restore_backup(restored_db, backup.backup_path)

    connection = connect(restored_db, require_exists=True)
    try:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
            for table in (
                "ap_suppliers",
                "ap_purchase_orders",
                "ap_purchase_order_lines",
                "ap_goods_receipts",
                "ap_goods_receipt_lines",
                "ap_supplier_invoices",
                "ap_supplier_invoice_lines",
                "ap_three_way_matches",
                "ap_idempotency_keys",
            )
        }
        assert counts == {
            "ap_suppliers": 1,
            "ap_purchase_orders": 1,
            "ap_purchase_order_lines": 1,
            "ap_goods_receipts": 1,
            "ap_goods_receipt_lines": 1,
            "ap_supplier_invoices": 1,
            "ap_supplier_invoice_lines": 1,
            "ap_three_way_matches": 1,
            "ap_idempotency_keys": 2,
        }
        assert (
            connection.execute(
                "SELECT status FROM ap_three_way_matches WHERE supplier_invoice_id = "
                "(SELECT id FROM ap_supplier_invoices WHERE invoice_number = ?)",
                ("INV-BACKUP",),
            ).fetchone()["status"]
            == "Passed"
        )
    finally:
        connection.close()
