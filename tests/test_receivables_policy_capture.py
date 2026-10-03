"""Actual AR lifecycle retains zero/three-place interpretation under rebind."""

from __future__ import annotations

import json
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest

from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.domain.finance_policy import POLICY_COLUMNS
from reconforge.domain.receivables_policy import require_aggregation_affinity, verify_receivables_policy
from reconforge.infrastructure.sqlite_receivables import SQLiteReceivablesRepository
from reconforge.io.persisted import decode_financial_idempotency_response, encode_financial_idempotency_response
from reconforge.platform.common import PlatformError, ensure_workspace
from reconforge.utils.money import CurrencyRegistryContext
from tests.test_receivables_credit_integrity import ReceivablesDatabase
from tests.test_receivables_credit_integrity import database as database
from tests.test_receivables_monetary_policy import POLICY_DIGESTS, REGISTRY_DIGEST, SNAPSHOT, record


def bind(database: ReceivablesDatabase, snapshot: dict) -> CurrencyRegistryContext:
    context = CurrencyRegistryContext.from_snapshot(snapshot)
    payload = json.dumps(context.snapshot(), sort_keys=True, separators=(",", ":"))
    digest = context.registry_manifest.digest
    version = context.registry_manifest.registry_version
    if database.path is not None:
        with closing(connect(database.path)) as connection:
            workspace = ensure_workspace(connection, "default")
            connection.execute("INSERT INTO currency_registry_snapshots(registry_digest,registry_version,snapshot_json,captured_at,captured_by) VALUES(?,?,?,'2026-10-03','synthetic') ON CONFLICT DO NOTHING", (digest, version, payload))
            connection.execute("INSERT INTO currency_registry_bindings(workspace_id,registry_version,registry_digest,bound_at,bound_by) VALUES(?,?,?,'2026-10-03','synthetic') ON CONFLICT(workspace_id) DO UPDATE SET registry_version=excluded.registry_version,registry_digest=excluded.registry_digest", (workspace, version, digest))
            connection.commit()
    else:
        with database.admin.transaction():
            for code, precision in (("JPY", 0), ("KWD", 3)):
                database.admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING", (database.tenant, code, code, precision))
            database.admin.execute("INSERT INTO reconforge.currency_registry_snapshots(tenant_id,registry_digest,registry_version,snapshot_json,captured_by) VALUES(%s,%s,%s,%s,'synthetic') ON CONFLICT DO NOTHING", (database.tenant, digest, version, payload))
            database.admin.execute("INSERT INTO reconforge.currency_registry_bindings(tenant_id,workspace_id,registry_version,registry_digest,bound_by) VALUES(%s,%s,%s,%s,'synthetic') ON CONFLICT(tenant_id,workspace_id) DO UPDATE SET registry_version=excluded.registry_version,registry_digest=excluded.registry_digest", (database.tenant, "workspace_"+database.tenant, version, digest))
    return context


@pytest.mark.parametrize("currency,precision", [("JPY", 0), ("KWD", 3)])
@pytest.mark.parametrize("change", ["source", "precision"])
def test_retained_policy_survives_rebind_and_exact_retry_without_new_effect(database: ReceivablesDatabase, currency: str, precision: int, change: str) -> None:
    bind(database, SNAPSHOT)
    with database.repository() as repo:
        customer = repo.upsert_customer(customer_code="POLICY", name="Synthetic", currency_code=currency, credit_limit_minor=10000, actor_label="maker")
        invoice = repo.create_invoice(invoice_number="POLICY", customer_code="POLICY", invoice_date="2026-10-01", currency_code=currency, tax_minor=0, lines=[ReceivableInvoiceLineInput("Synthetic", "1", 1234, 1234)], actor_label="maker")
        repo.submit_invoice(invoice["id"], expected_version=1, actor_label="maker")
        approved = repo.approve_invoice(invoice["id"], expected_version=2, actor_label="checker")
        body = dict(receipt_number="POLICY", customer_code="POLICY", receipt_date="2026-10-03", currency_code=currency, amount_minor=1000, allocations=(ReceiptAllocationInput(invoice["id"], 500),), idempotency_key="policy-retry", actor_label="cashier")
        receipt = repo.post_receipt(**body)
        for item in (customer, invoice, approved, receipt):
            policy = item["monetary_policy"]
            assert policy["status"] == "captured"
            assert policy["precision"] == precision
            assert policy["registry_digest"] == REGISTRY_DIGEST
            assert policy["policy_digest"] == POLICY_DIGESTS[currency]
        assert repo.get_invoice(invoice["id"])["outstanding_minor"] == 734
        assert receipt["unallocated_minor"] == 500
        before = database.evidence_counts()
        changed = deepcopy(SNAPSHOT)
        if change == "source":
            changed["source"] = "Synthetic replacement registry source"
        else:
            for spec in changed["currencies"]:
                if spec["code"] == currency:
                    spec["minor_units"] = precision + 1
        bind(database, changed)
        assert repo.get_customer(customer["id"])["monetary_policy"] == customer["monetary_policy"]
        assert repo.get_invoice(invoice["id"])["monetary_policy"] == invoice["monetary_policy"]
        assert repo.get_receipt(receipt["id"])["monetary_policy"] == receipt["monetary_policy"]
        assert repo.post_receipt(**body) == receipt
        with pytest.raises(PlatformError, match="policy_mismatch"):
            repo.allocate_receipt(receipt["id"], invoice_id=invoice["id"], amount_minor=100, expected_version=1, actor_label="cashier")
        with pytest.raises(PlatformError, match="policy_mismatch"):
            repo.create_invoice(invoice_number="NEW", customer_code="POLICY", invoice_date="2026-10-03", currency_code=currency, tax_minor=0, lines=[ReceivableInvoiceLineInput("Synthetic", "1", 1, 1)], actor_label="maker")
        assert database.evidence_counts() == before
        assert repo.get_invoice(invoice["id"])["outstanding_minor"] == 734
        assert repo.get_receipt(receipt["id"])["unallocated_minor"] == 500


def test_aging_rejects_cross_customer_same_currency_different_retained_policy(database: ReceivablesDatabase) -> None:
    bind(database, SNAPSHOT)
    with database.repository() as repo:
        for number in ("FIRST", "SECOND"):
            repo.upsert_customer(customer_code=number, name="Synthetic", currency_code="JPY", credit_limit_minor=10000, actor_label="maker")
            invoice = repo.create_invoice(invoice_number=number, customer_code=number, invoice_date="2026-10-01", currency_code="JPY", tax_minor=0, lines=[ReceivableInvoiceLineInput("Synthetic", "1", 1234, 1234)], actor_label="maker")
            repo.submit_invoice(invoice["id"], expected_version=1, actor_label="maker")
            repo.approve_invoice(invoice["id"], expected_version=2, actor_label="checker")
            changed = deepcopy(SNAPSHOT)
            changed["source"] = "Synthetic replacement registry source"
            bind(database, changed)
        for report in (repo.aging_report, repo.aging_report_by_currency):
            with pytest.raises(PlatformError, match="policy_mismatch"):
                report(as_of_date="2026-10-03")


def test_sqlite_ordinary_default_captures_without_inventing_currency_master(tmp_path: Path) -> None:
    path = tmp_path / "ordinary.db"
    run_migrations(path)
    with closing(connect(path)) as connection:
        repo = SQLiteReceivablesRepository(connection)
        connection.execute("DELETE FROM currencies WHERE code='USD'")
        connection.commit()
        assert connection.execute("SELECT COUNT(*) FROM currencies WHERE code='USD'").fetchone()[0] == 0
        saved = repo.upsert_customer(customer_code="CUS", name="Synthetic", currency_code="USD", credit_limit_minor=100)
        assert saved["monetary_policy"]["precision"] == 2
        assert connection.execute("SELECT COUNT(*) FROM currencies WHERE code='USD'").fetchone()[0] == 0


def test_sqlite_rejects_retained_noninteger_master_precision_before_effects(tmp_path: Path) -> None:
    path = tmp_path / "invalid-master.db"
    run_migrations(path)
    with closing(connect(path)) as connection:
        connection.execute("DELETE FROM currencies WHERE code='USD'")
        connection.execute("INSERT INTO currencies(code,name,minor_units,active,created_at,updated_at) VALUES('USD','Synthetic invalid master',2.5,1,'2026-10-03','2026-10-03')")
        connection.commit()
        assert connection.execute("SELECT typeof(minor_units) FROM currencies WHERE code='USD'").fetchone()[0] == "real"
        before = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("ar_customers", "currency_registry_snapshots", "audit_events", "outbox_events")}
        with pytest.raises(PlatformError, match="ar_monetary_policy_invalid"):
            SQLiteReceivablesRepository(connection).upsert_customer(customer_code="INVALID", name="Synthetic", currency_code="USD", credit_limit_minor=1234)
        after = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}
        assert after == before


def test_aggregation_keeps_all_legacy_raw_reads_but_rejects_mixed_policy() -> None:
    legacy = verify_receivables_policy({"currency_code": "JPY"})
    captured = verify_receivables_policy(record(), snapshot=SNAPSHOT)
    require_aggregation_affinity([legacy, legacy])
    require_aggregation_affinity([captured, captured])
    with pytest.raises(ValueError, match="unverified"):
        require_aggregation_affinity([legacy, captured])


@pytest.mark.parametrize("operation", ["invoice", "receipt"])
@pytest.mark.parametrize("tamper", ["tuple", "projection", "missing"])
def test_cached_policy_tamper_fails_before_any_effect(database: ReceivablesDatabase, operation: str, tamper: str) -> None:
    with database.repository() as repo:
        repo.upsert_customer(customer_code="CACHE", name="Synthetic", currency_code="USD", credit_limit_minor=10000, actor_label="maker")
        if operation == "invoice":
            create = repo.create_invoice
            body = dict(invoice_number="CACHE", customer_code="CACHE", invoice_date="2026-10-01", currency_code="USD", tax_minor=0, lines=[ReceivableInvoiceLineInput("Synthetic", "1", 1234, 1234)], idempotency_key="cache-policy", actor_label="maker")
        else:
            create = repo.post_receipt
            body = dict(receipt_number="CACHE", customer_code="CACHE", receipt_date="2026-10-03", currency_code="USD", amount_minor=1234, idempotency_key="cache-policy", actor_label="cashier")
        original = create(**body)
        assert create(**body) == original
        with closing(connect(database.path)) if database.path is not None else database.admin.transaction() as local:
            connection = local if database.path is not None else database.admin
            if database.path is not None:
                raw = connection.execute("SELECT response_json FROM ar_idempotency_keys WHERE idempotency_key='cache-policy'").fetchone()[0]
            else:
                raw = connection.execute("SELECT response_json::text FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s AND idempotency_key='cache-policy'", (database.tenant,)).fetchone()[0]
            cached = decode_financial_idempotency_response(raw).payload
            response = cached if operation == "invoice" else cached["response"]
            if tamper == "tuple":
                response["currency_precision"] = 0
            elif tamper == "projection":
                response["monetary_policy"]["precision"] = 0
            else:
                response.pop("monetary_policy")
            encoded = encode_financial_idempotency_response(cached).text
            if database.path is not None:
                connection.execute("UPDATE ar_idempotency_keys SET response_json=? WHERE idempotency_key='cache-policy'", (encoded,))
                connection.commit()
            else:
                connection.execute("UPDATE reconforge.ar_idempotency_keys SET response_json=%s::jsonb WHERE tenant_id=%s AND idempotency_key='cache-policy'", (encoded, database.tenant))
        before = database.evidence_counts()
        with pytest.raises(PlatformError, match="ar_monetary_policy_invalid"):
            create(**body)
        authoritative = repo.get_invoice(original["id"]) if operation == "invoice" else repo.get_receipt(original["id"])
        assert authoritative["monetary_policy"]["precision"] == 2
        assert database.evidence_counts() == before


@pytest.mark.parametrize("legacy", [False, True])
def test_sqlite_policy_backup_restore_preserves_captured_or_explicit_unresolved(tmp_path: Path, legacy: bool) -> None:
    path = tmp_path / "source.db"
    run_migrations(path, target_version=48 if legacy else 49)
    with closing(connect(path)) as connection:
        if legacy:
            from tests.test_receivables_policy_schema import legacy_customer

            legacy_customer(connection, "ΔΕΖ")
            identifier = "legacy"
        else:
            identifier = SQLiteReceivablesRepository(connection).upsert_customer(customer_code="KWD", name="Synthetic", currency_code="KWD", credit_limit_minor=1234)["id"]
    run_migrations(path)
    with closing(connect(path)) as connection:
        before = SQLiteReceivablesRepository(connection).get_customer(identifier)
    backup = create_backup(path, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)
    with closing(connect(restored)) as connection:
        after = SQLiteReceivablesRepository(connection).get_customer(identifier)
        assert after == before
        assert after["monetary_policy"]["status"] == ("unverified" if legacy else "captured")
        assert [after[column] for column in POLICY_COLUMNS] == [before[column] for column in POLICY_COLUMNS]
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='ar_customers_currency_policy_required'").fetchone()[0] == 1
