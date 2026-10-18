"""Aging must never sum minor units across currencies."""

from typing import Any

import pytest

from reconforge.api.routes.receivables import _filter_aging
from reconforge.api.server_identity import RequestExecutionScope
from reconforge.api.server_receivables import ReceivablesExecutionScope
from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from reconforge.auth.field_access import project_receivables_aging_by_currency
from reconforge.domain.receivables_aging import AgingCurrencyError, build_aging_report
from reconforge.platform.common import PlatformError
from tests.test_receivables_credit_integrity import ReceivablesDatabase, customer
from tests.test_receivables_credit_integrity import database as database


def open_invoice(repository: Any, currency: str, amount: int) -> dict[str, Any]:
    code = "CUS-" + currency
    customer(repository, customer_code=code, currency_code=currency, credit_limit_minor=10000)
    document = repository.create_invoice(
        invoice_number="INV-" + currency, customer_code=code, currency_code=currency,
        invoice_date="2026-07-01", due_date="2026-07-31", tax_minor=0,
        lines=[ReceivableInvoiceLineInput("Synthetic sale", "1", amount, amount)], actor_label="maker",
    )
    repository.submit_invoice(document["id"], expected_version=1, actor_label="maker")
    return repository.approve_invoice(document["id"], expected_version=2, actor_label="checker")


def seed_currency_registry(database: ReceivablesDatabase) -> None:
    if database.path is None:
        with database.admin.transaction():
            for currency, precision in (("JPY", 0), ("EGP", 2)):
                database.admin.execute(
                    "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,%s,%s,%s)",
                    (database.tenant, currency, currency, precision),
                )


def test_single_currency_aging_preserves_v1_values_and_labels_currency(database: ReceivablesDatabase) -> None:
    with database.repository() as repository:
        document = open_invoice(repository, "USD", 1200)
        report = repository.aging_report(as_of_date="2026-08-01")
        assert report["currency_code"] == "USD"
        assert report["as_of_date"] == "2026-08-01"
        assert report["total_outstanding_minor"] == 1200
        assert report["bucket_totals_minor"] == {"Current": 0, "1-30": 1200, "31-60": 0, "61-90": 0, "90+": 0}
        assert report["items"][0]["invoice_id"] == document["id"]


def test_empty_aging_has_no_implied_currency(database: ReceivablesDatabase) -> None:
    with database.repository() as repository:
        report = repository.aging_report(as_of_date="2026-08-01")
        assert report["currency_code"] is None
        assert report["items"] == []
        assert report["total_outstanding_minor"] == 0
        assert repository.aging_report_by_currency(as_of_date="2026-08-01") == {
            "schema_version": 1, "as_of_date": "2026-08-01", "currency_groups": [],
        }


def test_mixed_currency_v1_fails_closed_and_grouped_report_keeps_units_separate(database: ReceivablesDatabase) -> None:
    seed_currency_registry(database)
    with database.repository() as repository:
        for currency, amount in (("USD", 1200), ("JPY", 700), ("EGP", 3400)):
            open_invoice(repository, currency, amount)
        with pytest.raises(PlatformError, match="currency|currencies"):
            repository.aging_report(as_of_date="2026-08-01")
        report = repository.aging_report_by_currency(as_of_date="2026-08-01")
        assert set(report) == {"schema_version", "as_of_date", "currency_groups"}
        assert report["schema_version"] == 1
        assert report["as_of_date"] == "2026-08-01"
        assert [group["currency_code"] for group in report["currency_groups"]] == ["EGP", "JPY", "USD"]
        for group, expected in zip(report["currency_groups"], (3400, 700, 1200), strict=True):
            assert group["total_outstanding_minor"] == expected
            assert group["bucket_totals_minor"] == {"Current": 0, "1-30": expected, "31-60": 0, "61-90": 0, "90+": 0}
            assert len(group["items"]) == 1
            assert group["items"][0]["currency_code"] == group["currency_code"]
            assert group["items"][0]["outstanding_minor"] == expected


def test_paid_other_currency_does_not_block_single_open_currency(database: ReceivablesDatabase) -> None:
    with database.repository() as repository:
        open_invoice(repository, "USD", 1200)
        euro = open_invoice(repository, "EUR", 300)
        repository.post_receipt(
            receipt_number="EUR-PAID", customer_code="CUS-EUR", receipt_date="2026-08-01", currency_code="EUR",
            amount_minor=300, allocations=[ReceiptAllocationInput(euro["id"], 300)], actor_label="cashier",
        )
        report = repository.aging_report(as_of_date="2026-08-01")
        assert report["currency_code"] == "USD"
        assert report["total_outstanding_minor"] == 1200
        assert len(report["items"]) == 1


def test_aging_reaggregates_only_authorized_items_and_removes_hidden_currency_groups() -> None:
    items = [
        {"invoice_id": "visible", "organization_id": "org-a", "legal_entity_id": "entity-a", "currency_code": "USD", "bucket": "1-30", "outstanding_minor": 100},
        {"invoice_id": "hidden-entity", "organization_id": "org-a", "legal_entity_id": "entity-b", "currency_code": "USD", "bucket": "1-30", "outstanding_minor": 900},
        {"invoice_id": "hidden-org", "organization_id": "org-b", "legal_entity_id": "entity-b", "currency_code": "EUR", "bucket": "1-30", "outstanding_minor": 300},
    ]
    report = build_aging_report("2026-08-01", items, grouped=True)
    scope = ReceivablesExecutionScope(RequestExecutionScope("tenant", "workspace", "org-a", "entity-a"))
    filtered = _filter_aging(report, scope, grouped=True)
    assert len(filtered["currency_groups"]) == 1
    group = filtered["currency_groups"][0]
    assert group["currency_code"] == "USD"
    assert group["total_outstanding_minor"] == 100
    assert group["bucket_totals_minor"]["1-30"] == 100
    assert group["items"] == [{"invoice_id": "visible", "currency_code": "USD", "bucket": "1-30", "outstanding_minor": 100}]
    single = _filter_aging(report, scope)
    assert single["currency_code"] == "USD"
    assert single["total_outstanding_minor"] == 100


def test_grouped_aging_projection_closes_top_level_groups_and_items() -> None:
    report = build_aging_report("2026-08-01", [
        {"invoice_id": "visible", "currency_code": "JPY", "bucket": "Current", "outstanding_minor": 700, "unknown_item": "must-not-escape"},
    ], grouped=True)
    report["unknown_report"] = "must-not-escape"
    report["currency_groups"][0]["unknown_group"] = "must-not-escape"
    visible = project_receivables_aging_by_currency(report).visible
    assert set(visible) == {"schema_version", "as_of_date", "currency_groups"}
    assert visible["currency_groups"][0]["total_outstanding_minor"] == 700
    assert "must-not-escape" not in str(visible)


@pytest.mark.parametrize("amount", [True, 1.5, "100", -1, None])
def test_aging_rejects_invalid_minor_units_instead_of_coercing_them(amount: object) -> None:
    with pytest.raises(AgingCurrencyError, match="integer minor units"):
        build_aging_report("2026-08-01", [{"currency_code": "USD", "bucket": "Current", "outstanding_minor": amount}], grouped=True)
