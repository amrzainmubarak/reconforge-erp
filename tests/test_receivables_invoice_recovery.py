"""Two-engine invoice recovery, physical serialization, and atomic failure evidence."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import replace
from threading import Event

import pytest

from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from reconforge.db import connect
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesError
from reconforge.platform.common import PlatformError
from tests.test_receivables_credit_integrity import ReceivablesDatabase
from tests.test_receivables_credit_integrity import database as database
from tests.test_receivables_monetary_policy import SNAPSHOT
from tests.test_receivables_policy_capture import bind


def body(**changes) -> dict:
    return {"invoice_number": "PROOF", "customer_code": "PROOF", "invoice_date": "2026-10-03",
            "currency_code": "JPY", "tax_minor": 1, "lines": [ReceivableInvoiceLineInput("First", "2", 500, 1000, 1),
                                                               ReceivableInvoiceLineInput("Second", "1", 100, 100)],
            "idempotency_key": "proof-key", "actor_label": "maker", **changes}


def seed(database: ReceivablesDatabase) -> None:
    bind(database, SNAPSHOT)
    with database.repository() as repo:
        repo.upsert_customer(customer_code="PROOF", name="Synthetic", currency_code="JPY", credit_limit_minor=10000, payment_terms_days=7, actor_label="maker")


@contextmanager
def admin(database: ReceivablesDatabase):
    with closing(connect(database.path)) if database.path else database.admin.transaction() as local:
        yield local if database.path else database.admin


def state(database: ReceivablesDatabase) -> str:
    rows = {}
    tables = [(name, "") for name in ("ar_customers", "ar_invoices", "ar_invoice_lines", "ar_receipts", "ar_receipt_allocations", "ar_idempotency_keys")]
    tables += [("audit_events" if database.path else "domain_audit_events", "object_type"), ("outbox_events", "aggregate_type")]
    with admin(database) as connection:
        for table, field in tables:
            query = "SELECT * FROM " + ("" if database.path else "reconforge.") + table
            predicates = []
            if field:
                predicates.append(field + " IN ('ar_customer','ar_invoice','ar_receipt')")
            if not database.path:
                predicates.append("tenant_id=%s")
            if predicates:
                query += " WHERE " + " AND ".join(predicates)
            cursor = connection.execute(query) if database.path else connection.execute(query, (database.tenant,))
            columns = [column[0] for column in cursor.description]
            rows[table] = sorted([dict(zip(columns, row, strict=True)) for row in cursor.fetchall()], key=lambda row: json.dumps(row, sort_keys=True, default=str))
    return json.dumps(rows, sort_keys=True, default=str, separators=(",", ":"))


def cache(database: ReceivablesDatabase, value=None) -> dict:
    with admin(database) as connection:
        if database.path:
            original = connection.execute("SELECT response_json FROM ar_idempotency_keys WHERE idempotency_key='proof-key'").fetchone()[0]
            if value is not None:
                connection.execute("UPDATE ar_idempotency_keys SET response_json=? WHERE idempotency_key='proof-key'", (json.dumps(value),))
                connection.commit()
        else:
            original = connection.execute("SELECT response_json::text FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s AND idempotency_key='proof-key'", (database.tenant,)).fetchone()[0]
            if value is not None:
                connection.execute("UPDATE reconforge.ar_idempotency_keys SET response_json=%s::jsonb WHERE tenant_id=%s AND idempotency_key='proof-key'", (json.dumps(value), database.tenant))
    return json.loads(original)


def test_recovery_retains_creation_after_payment_inactivation_terms_and_registry_rebind(database: ReceivablesDatabase) -> None:
    seed(database)
    with database.repository() as repo:
        original = repo.create_invoice(**body())
        assert original["due_date"] == "2026-10-10"
        repo.submit_invoice(original["id"], expected_version=1, actor_label="maker")
        repo.approve_invoice(original["id"], expected_version=2, actor_label="checker")
        repo.post_receipt(receipt_number="PAID", customer_code="PROOF", receipt_date="2026-10-03", currency_code="JPY", amount_minor=1101,
                          allocations=[ReceiptAllocationInput(original["id"], 1101)], actor_label="cashier")
        repo.upsert_customer(customer_code="PROOF", name="Synthetic", currency_code="JPY", credit_limit_minor=10000,
                             payment_terms_days=90, status="Suspended", actor_label="maker")
        changed = deepcopy(SNAPSHOT)
        changed["source"] = "Synthetic changed registry"
        bind(database, changed)
        before = state(database)
        assert repo.create_invoice(**body(actor_label="second-authorized-manager")) == original
        assert repo.get_invoice(original["id"])["status"] == "Paid"
        assert repo.get_invoice(original["id"])["outstanding_minor"] == 0
        assert state(database) == before
        with pytest.raises(PlatformError, match="Active"):
            repo.create_invoice(**body(invoice_number="NEW", idempotency_key="new-key"))
        assert state(database) == before


def test_request_mismatch_and_foreign_cache_cannot_select_authoritative_invoice(database: ReceivablesDatabase) -> None:
    seed(database)
    with database.repository() as repo:
        original = repo.create_invoice(**body())
        foreign = repo.create_invoice(**body(invoice_number="FOREIGN", idempotency_key="other-key"))
        before = state(database)
        for change in ({"invoice_number": "FOREIGN"}, {"customer_code": "MISSING"}, {"invoice_date": "2026-10-04"},
                       {"due_date": "2026-10-10"}, {"lines": list(reversed(body()["lines"]))}):
            with pytest.raises(PlatformError):
                repo.create_invoice(**body(**change))
            assert state(database) == before
        retained = cache(database)
        retained["response"] = foreign
        cache(database, retained)
        before = state(database)
        with pytest.raises(PlatformError, match="acknowledgement"):
            repo.create_invoice(**body())
        assert state(database) == before
        assert repo.get_invoice(original["id"])["invoice_number"] == "PROOF"


@pytest.mark.parametrize("explicit", [False, True])
def test_raw_legacy_receipt_requires_provable_explicit_due_date(database: ReceivablesDatabase, explicit: bool) -> None:
    seed(database)
    request = body(**({"due_date": "2026-10-10"} if explicit else {}))
    with database.repository() as repo:
        original = repo.create_invoice(**request)
        cache(database, original)
        before = state(database)
        if explicit:
            assert repo.create_invoice(**request) == original
        else:
            with pytest.raises(PlatformError, match="omitted due-date.*read the existing invoice"):
                repo.create_invoice(**request)
        assert state(database) == before
        assert repo.get_invoice(original["id"]) == original


@pytest.mark.parametrize("target", ["key", "audit", "outbox"])
def test_late_insert_failure_rolls_back_invoice_lines_key_and_evidence(database: ReceivablesDatabase, target: str) -> None:
    seed(database)
    table = {"key": "ar_idempotency_keys", "audit": "audit_events" if database.path else "domain_audit_events", "outbox": "outbox_events"}[target]
    with database.repository() as repo:
        with admin(database) as connection:
            if database.path:
                connection.execute(f"CREATE TRIGGER invoice_recovery_fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'synthetic late failure'); END")
                connection.commit()
            else:
                connection.execute("CREATE FUNCTION reconforge.invoice_recovery_fault() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'synthetic late failure'; END$$")
                connection.execute(f"CREATE TRIGGER invoice_recovery_fault BEFORE INSERT ON reconforge.{table} FOR EACH ROW EXECUTE FUNCTION reconforge.invoice_recovery_fault()")
        before = state(database)
        try:
            with pytest.raises((PlatformError, PostgresReceivablesError)):
                repo.create_invoice(**body())
            assert state(database) == before
        finally:
            with admin(database) as connection:
                if database.path:
                    connection.execute("DROP TRIGGER invoice_recovery_fault")
                    connection.commit()
                else:
                    connection.execute(f"DROP TRIGGER invoice_recovery_fault ON reconforge.{table}")
                    connection.execute("DROP FUNCTION reconforge.invoice_recovery_fault()")
        original = repo.create_invoice(**body())
        before = state(database)
        assert repo.create_invoice(**body()) == original
        assert state(database) == before


@pytest.mark.parametrize("conflict", [False, True])
def test_two_physical_connections_serialize_same_scoped_key(database: ReceivablesDatabase, monkeypatch: pytest.MonkeyPatch, conflict: bool) -> None:
    seed(database)
    saved, release, second_ready, second_entered = Event(), Event(), Event(), Event()
    with database.repository() as repo:
        repository_type = type(repo)
    save = repository_type._save_idempotency

    def pause(self, operation, workspace_id, key, result):
        save(self, operation, workspace_id, key, result)
        if not saved.is_set():
            saved.set()
            assert release.wait(15)

    monkeypatch.setattr(repository_type, "_save_idempotency", pause)

    def create(second: bool):
        with database.repository() as repository:
            if second:
                second_ready.set()
                assert saved.wait(15)
                second_entered.set()
            else:
                assert second_ready.wait(15)
            return repository.create_invoice(**body(**({"invoice_number": "CONFLICT"} if second and conflict else {})))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(create, False)
        second = pool.submit(create, True)
        try:
            assert saved.wait(15)
            assert second_entered.wait(10)
            with pytest.raises(TimeoutError):
                second.result(timeout=0.15)
        finally:
            release.set()
        original = first.result(timeout=15)
        if conflict:
            with pytest.raises(PlatformError):
                second.result(timeout=15)
        else:
            assert second.result(timeout=15) == original
    with database.repository() as repo:
        before = state(database)
        assert repo.create_invoice(**body()) == original
        assert state(database) == before
    rows = json.loads(state(database))
    assert len(rows["ar_invoices"]) == len(rows["ar_idempotency_keys"]) == 1
    assert len(rows["ar_invoice_lines"]) == 2
    assert len([row for row in rows["outbox_events"] if row["aggregate_type"] == "ar_invoice"]) == 1


def test_authoritative_numeric_quantity_cannot_contradict_retained_text(database: ReceivablesDatabase) -> None:
    seed(database)
    with database.repository() as repo:
        original = repo.create_invoice(**body())
        with admin(database) as connection:
            if database.path:
                connection.execute("UPDATE ar_invoice_lines SET quantity='9' WHERE invoice_id=? AND line_number=1", (original["id"],))
                connection.commit()
            else:
                connection.execute("UPDATE reconforge.ar_invoice_lines SET quantity=9 WHERE tenant_id=%s AND invoice_id=%s AND line_number=1", (database.tenant, original["id"]))
        before = state(database)
        with pytest.raises((PlatformError, PostgresReceivablesError)):
            repo.create_invoice(**body())
        assert state(database) == before


def test_corrupt_receipt_header_lines_wrapper_and_policy_fail_closed(database: ReceivablesDatabase) -> None:
    seed(database)
    with database.repository() as repo:
        repo.create_invoice(**body())
        retained = cache(database)
        corruptions = []
        for field, value in (("created_by", "forged"), ("created_at", "forged"), ("total_minor", 9000), ("row_version", True),
                             ("currency_precision", 5), ("extra", "unknown")):
            changed = deepcopy(retained)
            changed["response"][field] = value
            corruptions.append(changed)
        for field, value in (("id", "foreign"), ("invoice_id", "foreign"), ("line_number", True), ("created_at", "forged"),
                             ("tax_minor", False), ("extra", "unknown")):
            changed = deepcopy(retained)
            changed["response"]["lines"][0][field] = value
            corruptions.append(changed)
        missing = deepcopy(retained)
        missing["response"]["lines"][0].pop("unit_price_minor")
        corruptions.extend([missing, {**retained, "extra": 1}, {**retained, "schema_version": True}, {**retained, "request_digest": "0" * 64}])
        for corrupt in corruptions:
            cache(database, corrupt)
            before = state(database)
            with pytest.raises((PlatformError, PostgresReceivablesError)):
                repo.create_invoice(**body())
            assert state(database) == before
        cache(database, retained)
        assert repo.create_invoice(**body()) == retained["response"]


def test_encode_budget_failure_after_insert_has_no_persisted_effect(database: ReceivablesDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    import reconforge.io.persisted as codec

    seed(database)
    observed = []
    with database.repository() as repo:
        save = type(repo)._save_idempotency

        def bounded_save(self, operation, workspace_id, key, result):
            prefix = "" if database.path else "reconforge."
            scope = "" if database.path else " WHERE tenant_id=%s"
            counts = []
            for table in ("ar_invoices", "ar_invoice_lines", "ar_idempotency_keys"):
                query = "SELECT count(*) FROM " + prefix + table + scope
                cursor = self.connection.execute(query) if database.path else self.connection.execute(query, (database.tenant,))
                counts.append(cursor.fetchone()[0])
            observed.append(counts)
            with monkeypatch.context() as patch:
                patch.setattr(codec, "FINANCIAL_IDEMPOTENCY_JSON_POLICY", replace(codec.FINANCIAL_IDEMPOTENCY_JSON_POLICY, max_file_bytes=128))
                save(self, operation, workspace_id, key, result)

        monkeypatch.setattr(type(repo), "_save_idempotency", bounded_save)
        before = state(database)
        with pytest.raises((PlatformError, PostgresReceivablesError)):
            repo.create_invoice(**body())
        assert observed == [[1, 2, 0]]
        assert state(database) == before
