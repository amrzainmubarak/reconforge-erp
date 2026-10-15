"""Adversarial monetary AR read contracts; cursors here are not native proof."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from reconforge.infrastructure import postgres_monetary_receivables as monetary
from reconforge.infrastructure import postgres_receivables as ar
from reconforge.platform.common import PlatformError
from tests.test_receivables_partial_schema_compatibility import (
    Connection,
    Result,
    project,
    repository,
)


def balance() -> dict[str, Any]:
    return {
        "schema_version": "stock-monetary-balance-v1", "history_version": 4,
        "history_fingerprint": "c" * 64, "active_plan_id": "CR3-" + "a" * 32,
        "active_revaluation_plan_id": None,
        "transaction_original_gross_minor": "1000", "functional_original_gross_minor": "1500",
        "transaction_collected_minor": "800", "transaction_credited_minor": "400",
        "transaction_outstanding_minor": "0", "functional_outstanding_minor": "0",
        "transaction_refund_entitlement_minor": "200", "functional_refund_entitlement_minor": "300",
        "transaction_refunded_minor": "50", "functional_refund_released_minor": "75",
        "transaction_refund_due_minor": "150", "functional_refund_due_minor": "225",
    }


class Catalog:
    def __init__(self, row: Any) -> None:
        self.row = row
        self.calls = 0

    def execute(self, query: str) -> Result:
        assert query == monetary.MONETARY_SCHEMA_SQL
        self.calls += 1
        return Result({"profile": self.row})


@pytest.mark.parametrize("complete", [False, True])
def test_catalog_absence_or_presence_is_rechecked_without_cache(complete: bool) -> None:
    cursor = Catalog(dict.fromkeys(monetary.CATALOG_FIELDS, complete))
    assert monetary.monetary_return_schema(cursor) is complete
    cursor.row = dict.fromkeys(monetary.CATALOG_FIELDS, not complete)
    assert monetary.monetary_return_schema(cursor) is not complete
    assert cursor.calls == 2


@pytest.mark.parametrize("field", monetary.CATALOG_FIELDS)
@pytest.mark.parametrize("otherwise_complete", [False, True])
def test_any_partial_relation_or_helper_never_falls_back(field: str, otherwise_complete: bool) -> None:
    row = dict.fromkeys(monetary.CATALOG_FIELDS, otherwise_complete)
    row[field] = not otherwise_complete
    with pytest.raises(PlatformError, match="incomplete or malformed"):
        monetary.monetary_return_schema(Catalog(row))


@pytest.mark.parametrize("row", [None, {}, (), (True,), [1] * 18,
                                {**dict.fromkeys(monetary.CATALOG_FIELDS, False), "extra": False}])
def test_missing_or_coerced_catalog_evidence_refuses(row: Any) -> None:
    with pytest.raises(PlatformError, match="cannot be verified"):
        monetary.monetary_return_schema(Catalog(row))


@pytest.mark.parametrize("value", [False, 1, Decimal("1"), 1.5, "-1", "+1", "01", " 1", "1.0", "1e2", "", "NaN", "١", "9" * 20])
def test_minor_text_never_truncates_coerces_or_accepts_noncanonical_values(value: Any) -> None:
    with pytest.raises(PlatformError):
        monetary.natural_minor_text(value)


def test_exposure_aggregate_has_no_per_invoice_cap() -> None:
    assert monetary.natural_minor_text("18000000000000000000", bounded=False) == 18_000_000_000_000_000_000


@pytest.mark.parametrize("prefix", ["FX1", "CR3", "CRF3", "CR3R", "CRF3R"])
def test_retained_foreign_refund_and_carrying_prefix(prefix: str) -> None:
    value = balance()
    value.update(active_plan_id=prefix + "-" + "b" * 32, active_revaluation_plan_id="FX1-" + "d" * 32)
    assert monetary.monetary_invoice_balance(value, total_minor=1000, allocated_minor=800) == value


@pytest.mark.parametrize(("field", "invalid"), [
    ("schema_version", "legacy"), ("history_version", True), ("history_version", 257),
    ("history_fingerprint", "A" * 64), ("active_plan_id", "CR2-" + "a" * 32),
    ("active_plan_id", "CR3" + "a" * 32),
    ("active_revaluation_plan_id", "CR3-" + "a" * 32),
    ("transaction_original_gross_minor", "1001"), ("functional_original_gross_minor", "0"),
    ("transaction_collected_minor", "799"), ("transaction_credited_minor", "1001"),
    ("transaction_outstanding_minor", "1"), ("functional_outstanding_minor", "1"),
    ("transaction_refund_entitlement_minor", "201"), ("transaction_refunded_minor", "201"),
    ("transaction_refund_due_minor", "151"), ("functional_refund_due_minor", "226"),
    ("functional_refund_released_minor", "301"),
])
def test_closed_balance_rejects_inconsistent_ar_or_carrying_authority(field: str, invalid: Any) -> None:
    value = balance()
    value[field] = invalid
    with pytest.raises(PlatformError):
        monetary.monetary_invoice_balance(value, total_minor=1000, allocated_minor=800)


@pytest.mark.parametrize("field", tuple(monetary.BALANCE_FIELDS))
def test_missing_balance_field_always_refuses(field: str) -> None:
    value = balance()
    value.pop(field)
    with pytest.raises(PlatformError, match="absent or malformed"):
        monetary.monetary_invoice_balance(value, total_minor=1000, allocated_minor=800)


def test_final_foreign_refund_cannot_leave_hidden_functional_liability() -> None:
    value = balance()
    value.update(transaction_refunded_minor="200", transaction_refund_due_minor="0")
    with pytest.raises(PlatformError, match="carrying conservation"):
        monetary.monetary_invoice_balance(value, total_minor=1000, allocated_minor=800)
    value.update(functional_refund_released_minor="300", functional_refund_due_minor="0")
    assert monetary.monetary_invoice_balance(value, total_minor=1000, allocated_minor=800) == value


@pytest.mark.parametrize("hidden_release", [False, True])
def test_no_functional_entitlement_or_release_without_its_foreign_prefix(hidden_release: bool) -> None:
    value = balance()
    value.update(transaction_refunded_minor="0", functional_refund_released_minor="1",
                 transaction_refund_due_minor="200", functional_refund_due_minor="299")
    if not hidden_release:
        # Independent C counterexample: no foreign entitlement/refund, yet a
        # fabricated exhausted L liability that a final-due-only check misses.
        value.update(transaction_collected_minor="600", transaction_refund_entitlement_minor="0",
                     transaction_refund_due_minor="0", functional_refund_entitlement_minor="1",
                     functional_refund_due_minor="0")
    with pytest.raises(PlatformError, match="carrying conservation"):
        monetary.monetary_invoice_balance(value, total_minor=1000, allocated_minor=800 if hidden_release else 600)


def test_positive_foreign_entitlement_and_refund_may_have_zero_functional_value() -> None:
    value = balance()
    value.update(functional_refund_entitlement_minor="0", functional_refund_released_minor="0", functional_refund_due_minor="0")
    assert monetary.monetary_invoice_balance(value, total_minor=1000, allocated_minor=800) == value


@pytest.mark.parametrize("overcollection", [False, True])
def test_cumulative_collection_and_functional_entitlement_cannot_exceed_original_gross(overcollection: bool) -> None:
    value = balance()
    collected = 800
    if overcollection:
        collected = 1001
        value.update(transaction_collected_minor="1001", transaction_refund_entitlement_minor="401", transaction_refund_due_minor="351")
    else:
        value.update(functional_refund_entitlement_minor="1501", functional_refund_due_minor="1426")
    with pytest.raises(PlatformError, match="carrying conservation"):
        monetary.monetary_invoice_balance(value, total_minor=1000, allocated_minor=collected)


@pytest.mark.parametrize("extra", [True, False])
def test_balance_has_no_extension_or_implicit_integer_coercion(extra: bool) -> None:
    value = balance()
    if extra:
        value["trusted"] = True
    else:
        value["transaction_credited_minor"] = 400
    with pytest.raises(PlatformError):
        monetary.monetary_invoice_balance(value, total_minor=1000, allocated_minor=800)


class MonetaryConnection(Connection):
    def __init__(self) -> None:
        super().__init__((False,) * 10)
        self.catalog = dict.fromkeys(monetary.CATALOG_FIELDS, True)
        self.balance: Any = balance()
        self.aggregate: Any = "0"
        self.credited: Any = "400"

    def execute(self, query: str, args: Any = None) -> Result:
        if query.startswith("WITH monetary_helpers AS"):
            self.calls.append((query, args))
            return Result({"profile": self.catalog})
        if query.startswith("SELECT COALESCE(SUM(greatest"):
            self.calls.append((query, args))
            return Result((self.aggregate,))
        if query.startswith("SELECT i.id,i.organization_id"):
            result = super().execute(query, args)
            result.value[0].update(total_minor=1000, allocated_minor="800", credited_minor=self.credited)
            return result
        result = super().execute(query, args)
        if query.startswith("SELECT id,workspace_id"):
            result.value["total_minor"] = 1000
            if "AS monetary_owner_balance" in query:
                result.value.update(monetary_allocated_minor="800", monetary_owner_balance=self.balance)
        if query.startswith("SELECT COALESCE(SUM(amount_minor),0)"):
            return Result((800,))
        return result


def monetary_repository(monkeypatch: pytest.MonkeyPatch) -> tuple[ar.PostgresReceivablesRepository, MonetaryConnection]:
    repo, _ = repository((False,) * 10, monkeypatch)
    connection = MonetaryConnection()
    repo.connection = connection
    return repo, connection


def test_actual_ar_reads_apply_credit_once_and_keep_foreign_units(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = monetary_repository(monkeypatch)
    invoice = project(repo, "invoice")
    assert (invoice["allocated_minor"], invoice["credited_minor"], invoice["refund_due_minor"], invoice["outstanding_minor"]) == (800, 400, 150, 0)
    assert "partial_return_source_id" not in invoice
    assert not {"monetary_allocated_minor", "monetary_owner_balance"} & invoice.keys()
    # Header/status/version, actual allocations and the STABLE public owner
    # projection are captured by the same SQL command, with no parent UPDATE
    # privilege or shared-lock upgrade introduced for read-only callers.
    header = next(query for query, _ in connection.calls if query.startswith("SELECT id,workspace_id"))
    assert "status," in header and "row_version," in header
    assert "SUM(a.amount_minor)" in header and "reconforge.monetary_stock_invoice_balance(" in header
    assert not any(query.startswith("SELECT COALESCE(SUM(amount_minor)") or "FOR SHARE" in query for query, _ in connection.calls)
    assert project(repo, "exposure") == 0
    assert project(repo, "aging")["items"] == []
    connection.credited = "100"
    assert project(repo, "aging")["items"][0]["outstanding_minor"] == 100
    queries = [query for query, _ in connection.calls if query.startswith(("SELECT i.id", "SELECT COALESCE(SUM(greatest"))]
    assert all(query.count("reconforge.monetary_stock_invoice_credit(") == 1 for query in queries)
    assert all("customer_partial_return_source_id" not in query for query in queries)


def test_genuinely_unowned_invoice_keeps_legacy_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = monetary_repository(monkeypatch)
    connection.balance = None
    invoice = project(repo, "invoice")
    assert invoice["outstanding_minor"] == 200
    assert "credited_minor" not in invoice


def test_old_and_new_owners_cannot_both_claim_an_invoice(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = monetary_repository(monkeypatch)
    connection.flags, connection.owned = (True,) * 10, True
    with pytest.raises(PlatformError, match="conflicting original-source"):
        project(repo, "invoice")


def test_both_installed_protocols_use_their_own_credit_once(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = monetary_repository(monkeypatch)
    connection.flags = (True,) * 10
    connection.aggregate = "123"
    assert project(repo, "exposure") == 123
    query = connection.calls[-1][0]
    assert query.count("reconforge.monetary_stock_invoice_credit(") == 1
    assert query.count("reconforge.customer_partial_return_credit(") == 1


def test_native_visibility_refusal_is_never_treated_as_unowned(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = monetary_repository(monkeypatch)
    execute = connection.execute

    def deny(query: str, args: Any = None) -> Result:
        if query.startswith("SELECT id,workspace_id") and "reconforge.monetary_stock_invoice_balance(" in query:
            raise RuntimeError("Native owner visibility refusal")
        return execute(query, args)

    monkeypatch.setattr(connection, "execute", deny)
    with pytest.raises(RuntimeError, match="visibility refusal"):
        project(repo, "invoice")


@pytest.mark.parametrize("kind", ["invoice", "exposure", "aging"])
def test_partial_monetary_migration_refuses_all_ar_read_paths(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = monetary_repository(monkeypatch)
    connection.catalog[monetary.CATALOG_FIELDS[0]] = False
    with pytest.raises(PlatformError, match="schema integration"):
        project(repo, kind)
    assert len(connection.calls) == 2
    assert all(query.startswith("WITH ") for query, _ in connection.calls)


@pytest.mark.parametrize("kind", ["exposure", "aging"])
@pytest.mark.parametrize("invalid", [Decimal("0.5"), "0.5", 0.5, True, "-1", None])
def test_report_results_cannot_truncate_bad_native_credit(kind: str, invalid: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = monetary_repository(monkeypatch)
    connection.aggregate = invalid
    connection.credited = invalid
    with pytest.raises(PlatformError):
        project(repo, kind)
