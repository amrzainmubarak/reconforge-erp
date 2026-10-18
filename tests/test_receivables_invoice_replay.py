"""Invoice creation recovery must prove the requested immutable financial source."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.infrastructure.sqlite_receivables import SQLiteReceivablesRepository
from reconforge.platform.common import PlatformError, ensure_workspace, platform_id
from tests.test_receivables import _service


def _request() -> dict:
    return dict(invoice_number="REPLAY", customer_code="CUSTOMER", invoice_date="2026-10-03",
                currency_code="USD", tax_minor=0, lines=[ReceivableInvoiceLineInput("Synthetic", "1", 1234, 1234)],
                idempotency_key="invoice-replay", actor_label="prep")


def _counts(connection) -> tuple:
    tables = ("ar_invoices", "ar_invoice_lines", "ar_idempotency_keys")
    result = tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables)
    return result + (connection.execute("SELECT count(*) FROM audit_events WHERE object_type='ar_invoice'").fetchone()[0],
                     connection.execute("SELECT count(*) FROM outbox_events WHERE aggregate_type='ar_invoice'").fetchone()[0])


def test_invoice_retry_rejects_different_request_without_effects(tmp_path: Path) -> None:
    connection, service = _service(tmp_path)
    try:
        service.upsert_customer(customer_code="CUSTOMER", name="Synthetic", currency_code="USD", credit_limit_minor=10000, actor_label="prep")
        request = _request()
        service.create_invoice(**request)
        before = _counts(connection)
        for change in ({"invoice_number": "OTHER"}, {"customer_code": "MISSING"},
                       {"lines": [ReceivableInvoiceLineInput("Synthetic", "1", 2345, 2345)]},
                       {"due_date": "2026-12-31"}, {"currency_code": "JPY"}):
            with pytest.raises(PlatformError):
                service.create_invoice(**{**request, **change})
            assert _counts(connection) == before
    finally:
        connection.close()


def test_invoice_retry_rejects_fabricated_cached_amount(tmp_path: Path) -> None:
    connection, service = _service(tmp_path)
    try:
        service.upsert_customer(customer_code="CUSTOMER", name="Synthetic", currency_code="USD", credit_limit_minor=10000, actor_label="prep")
        request = _request()
        invoice = service.create_invoice(**request)
        cached = json.loads(connection.execute("SELECT response_json FROM ar_idempotency_keys").fetchone()[0])
        modified = deepcopy(cached)
        response = modified.get("response", modified)
        response.update(subtotal_minor=2345, total_minor=2345, outstanding_minor=2345)
        response["lines"][0].update(unit_price_minor=2345, line_total_minor=2345)
        connection.execute("UPDATE ar_idempotency_keys SET response_json=?", (json.dumps(modified),))
        connection.commit()
        before = _counts(connection)
        with pytest.raises(PlatformError):
            service.create_invoice(**request)
        assert _counts(connection) == before
        assert service.get_invoice(invoice["id"])["total_minor"] == 1234
    finally:
        connection.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_backup_restore_retains_original_ack_after_full_payment(tmp_path: Path, legacy: bool) -> None:
    connection, service = _service(tmp_path)
    request = {**_request(), **({"due_date": "2026-10-10"} if legacy else {})}
    try:
        service.upsert_customer(customer_code="CUSTOMER", name="Synthetic", currency_code="USD", credit_limit_minor=10000, actor_label="prep")
        original = service.create_invoice(**request)
        service.submit_invoice(original["id"], expected_version=1, actor_label="prep")
        service.approve_invoice(original["id"], expected_version=2, actor_label="review")
        service.post_receipt(receipt_number="PAID", customer_code="CUSTOMER", receipt_date="2026-10-03", currency_code="USD", amount_minor=1234,
                             allocations=[ReceiptAllocationInput(original["id"], 1234)], actor_label="prep")
        if legacy:
            connection.execute("UPDATE ar_idempotency_keys SET response_json=?", (json.dumps(original),))
            connection.commit()
        retained = connection.execute("SELECT response_json FROM ar_idempotency_keys").fetchone()[0]
    finally:
        connection.close()
    backup = create_backup(tmp_path / "receivables.db", tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)
    connection = connect(restored)
    try:
        repo = SQLiteReceivablesRepository(connection)
        assert connection.execute("SELECT response_json FROM ar_idempotency_keys").fetchone()[0] == retained
        before = _counts(connection)
        assert repo.create_invoice(**request) == original
        assert repo.get_invoice(original["id"])["status"] == "Paid"
        assert repo.get_invoice(original["id"])["outstanding_minor"] == 0
        assert _counts(connection) == before
    finally:
        connection.close()


def test_internal_byte_budget_failure_rolls_back_all_creation_effects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    import reconforge.io.persisted as codec

    connection, service = _service(tmp_path)
    try:
        service.upsert_customer(customer_code="CUSTOMER", name="Synthetic", currency_code="USD", credit_limit_minor=10000, actor_label="prep")
        before = _counts(connection)
        monkeypatch.setattr(codec, "FINANCIAL_IDEMPOTENCY_JSON_POLICY", replace(codec.FINANCIAL_IDEMPOTENCY_JSON_POLICY, max_file_bytes=128))
        with pytest.raises(PlatformError, match="safety validation"):
            service.create_invoice(**_request())
        assert _counts(connection) == before
        assert connection.execute("SELECT count(*) FROM ar_invoices").fetchone()[0] == 0
    finally:
        connection.close()


def test_true_pre49_raw_ack_survives_upgrade_and_restore_without_inferred_policy(tmp_path: Path) -> None:
    source = tmp_path / "old.db"
    run_migrations(source, target_version=48)
    connection = connect(source)
    try:
        workspace = ensure_workspace(connection, "default")
        customer = platform_id("ARCUS", workspace, "OLD")
        invoice = platform_id("ARINV", workspace, customer, "OLD")
        connection.execute("INSERT INTO ar_customers(id,workspace_id,customer_code,name,currency_code,credit_limit_minor,created_at,updated_at) VALUES(?,?,'OLD','Synthetic old customer','USD',1000,'2026-01-01','2026-01-01')", (customer, workspace))
        connection.execute("INSERT INTO ar_invoices(id,workspace_id,customer_id,invoice_number,invoice_date,due_date,currency_code,subtotal_minor,tax_minor,total_minor,created_by,created_at,updated_at) VALUES(?,?,?,'OLD','2026-01-01','2026-01-08','USD',100,0,100,'historical-label','2026-01-01','2026-01-01')", (invoice, workspace, customer))
        connection.execute("INSERT INTO ar_invoice_lines(id,invoice_id,line_number,description,quantity,unit_price_minor,tax_minor,line_total_minor,created_at) VALUES(?,?,1,'Synthetic','1',100,0,100,'2026-01-01')", (platform_id("ARINVL", invoice, 1), invoice))
        original = dict(connection.execute("SELECT * FROM ar_invoices WHERE id=?", (invoice,)).fetchone())
        original.update(lines=[dict(row) for row in connection.execute("SELECT * FROM ar_invoice_lines WHERE invoice_id=?", (invoice,)).fetchall()], allocated_minor=0, outstanding_minor=100)
        connection.execute("INSERT INTO ar_idempotency_keys(scope,idempotency_key,response_json,created_at) VALUES(?,?,?,'2026-01-01')", ("invoice:" + workspace, "old-key", json.dumps(original)))
        connection.commit()
    finally:
        connection.close()
    run_migrations(source)
    backup = create_backup(source, tmp_path / "old-backup")
    restored = tmp_path / "old-restored.db"
    restore_backup(restored, backup.backup_path)
    connection = connect(restored)
    try:
        repo = SQLiteReceivablesRepository(connection)
        request = dict(invoice_number="OLD", customer_code="OLD", invoice_date="2026-01-01", due_date="2026-01-08",
                       currency_code="USD", tax_minor=0, lines=[ReceivableInvoiceLineInput("Synthetic", "1", 100, 100)], idempotency_key="old-key")
        assert repo.create_invoice(**request) == original
        assert "monetary_policy" not in original
        assert repo.get_invoice(invoice)["monetary_policy"]["status"] == "unverified"
        with pytest.raises(PlatformError, match="omitted due-date"):
            repo.create_invoice(**{**request, "due_date": ""})
    finally:
        connection.close()
