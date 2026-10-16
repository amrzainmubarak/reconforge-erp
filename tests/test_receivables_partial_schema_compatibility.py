"""Explicit old/native schema reads; synthetic cursors are not native proof."""
from contextlib import nullcontext
from itertools import product
from typing import Any

import pytest

from reconforge.infrastructure import postgres_receivables as module
from reconforge.infrastructure.postgres_monetary_receivables import CATALOG_FIELDS
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.platform.common import PlatformError

NAMES = ("marker_present", "source_present", "credit_present", "close_present", "balance_present",
         "marker_valid", "source_valid", "credit_valid", "close_valid", "balance_valid")


class Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def fetchone(self) -> Any:
        return self.value

    def fetchall(self) -> list[Any]:
        return self.value


class Connection:
    def __init__(self, flags: Any, *, owned: bool = False) -> None:
        self.flags, self.owned = flags, owned
        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: str, args: Any = None) -> Result:
        self.calls.append((query, args))
        if query.startswith("WITH marker AS"):
            return Result(self.flags)
        if query.startswith("WITH monetary_helpers AS"):
            return Result({"profile": dict.fromkeys(CATALOG_FIELDS, False)})
        if query.startswith("SELECT id,workspace_id"):
            row: dict[str, Any] = dict.fromkeys(PostgresReceivablesRepository._INVOICE, "")
            row.update(id="invoice", total_minor=45000, status="Approved", cancel_reason="", row_version=3)
            if "customer_partial_return_source_id" in query:
                row["customer_partial_return_source_id"] = "native-source" if self.owned else None
            return Result(row)
        if query.startswith("SELECT id,invoice_id,line_number"):
            return Result([])
        if query.startswith("SELECT COALESCE(SUM(amount_minor),0)"):
            return Result((10000,))
        if query.startswith("SELECT reconforge.customer_partial_return_source_close"):
            return Result(None)
        if query.startswith("SELECT reconforge.customer_partial_return_balance"):
            return Result({"value": {"credited_minor": 36000, "refund_due_minor": 1000, "outstanding_minor": 0}})
        if query.startswith("SELECT COALESCE(SUM(greatest"):
            return Result((20000 if "customer_partial_return_credit" in query else 35000,))
        if query.startswith("SELECT i.id,i.organization_id"):
            return Result([{"id": "invoice", "organization_id": "org", "legal_entity_id": "entity", "invoice_number": "INV",
                "customer_code": "CUSTOMER", "customer_name": "Synthetic", "currency_code": "USD", "invoice_date": "2026-10-01",
                "due_date": "2026-10-02", "total_minor": 45000, "allocated_minor": 10000,
                "credited_minor": 15000 if "customer_partial_return_credit" in query else 0,
                "currency_precision": 2, "currency_rounding_policy": "ROUND_HALF_UP", "currency_registry_version": "retained",
                "currency_registry_digest": "a" * 64}])
        raise AssertionError("Unexpected synthetic query")


def repository(flags: Any, monkeypatch: pytest.MonkeyPatch, *, owned: bool = False) -> tuple[PostgresReceivablesRepository, Connection]:
    connection = Connection(flags, owned=owned)
    repo = object.__new__(PostgresReceivablesRepository)
    repo.connection, repo.tenant_id = connection, "synthetic"
    monkeypatch.setattr(repo, "_with_policy", lambda row: row)
    monkeypatch.setattr(repo, "_transaction", nullcontext)
    monkeypatch.setattr(repo, "_required_workspace_id", lambda workspace: "work")
    monkeypatch.setattr(repo, "_policy", lambda row: None)
    monkeypatch.setattr(module, "require_aggregation_affinity", lambda values: None)
    monkeypatch.setattr(module, "build_aging_report", lambda as_of, items, grouped: {"items": items})
    return repo, connection


def project(repo: PostgresReceivablesRepository, kind: str) -> Any:
    if kind == "invoice":
        return repo._invoice("invoice")
    if kind == "exposure":
        return repo._exposure("customer")
    return repo.aging_report(workspace="work", as_of_date="2026-10-15")


@pytest.mark.parametrize("native", [False, True])
def test_each_projection_selects_the_complete_native_or_explicit_legacy_contract(native: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = repository(dict.fromkeys(NAMES, native), monkeypatch, owned=native)
    invoice = project(repo, "invoice")
    assert invoice["allocated_minor"] == 10000 and invoice["outstanding_minor"] == (0 if native else 35000)
    if native:
        assert (invoice["partial_return_source_id"], invoice["credited_minor"], invoice["refund_due_minor"]) == ("native-source", 36000, 1000)
    else:
        assert not {"partial_return_source_id", "credited_minor", "refund_due_minor"} & invoice.keys()
    assert project(repo, "exposure") == (20000 if native else 35000)
    aging = project(repo, "aging")
    assert aging["items"][0]["outstanding_minor"] == (20000 if native else 35000)
    probes = [query for query, _ in connection.calls if query.startswith("WITH marker AS")]
    assert len(probes) == 3
    financial = [query for query, _ in connection.calls if not query.startswith(("WITH marker AS", "WITH monetary_helpers AS"))]
    assert any("customer_partial_return_credit" in query for query in financial) is native
    if not native:
        assert all("customer_partial_return" not in query for query in financial)


PARTIAL = [flags for flags in product((False, True), repeat=5) if any(flags) and not all(flags)]


@pytest.mark.parametrize("flags", PARTIAL)
@pytest.mark.parametrize("kind", ["invoice", "exposure", "aging"])
def test_every_partial_installation_refuses_before_financial_projection(flags: tuple[bool, ...], kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = repository(dict(zip(NAMES, (*flags, *flags), strict=True)), monkeypatch)
    with pytest.raises(PlatformError, match="schema integration"):
        project(repo, kind)
    assert len(connection.calls) == 1 and connection.calls[0][0].startswith("WITH marker AS")


@pytest.mark.parametrize("field", NAMES[5:])
@pytest.mark.parametrize("kind", ["invoice", "exposure", "aging"])
def test_malformed_native_column_rls_or_helper_profile_never_uses_legacy_math(field: str, kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    flags = dict.fromkeys(NAMES, True)
    flags[field] = False
    repo, connection = repository(flags, monkeypatch)
    with pytest.raises(PlatformError, match="schema integration"):
        project(repo, kind)
    assert len(connection.calls) == 1


@pytest.mark.parametrize("bad", [None, {}, (True,), {**dict.fromkeys(NAMES, True), "marker_present": 1},
                                {**dict.fromkeys(NAMES, False), "marker_present": "false"}])
def test_missing_or_coerced_catalog_evidence_refuses(bad: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = repository(bad, monkeypatch)
    with pytest.raises(PlatformError, match="schema integration"):
        repo._partial_return_schema()
    assert len(connection.calls) == 1


def test_no_cached_absence_or_presence_survives_a_schema_change(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, connection = repository(dict.fromkeys(NAMES, False), monkeypatch)
    assert repo._partial_return_schema() is False
    connection.flags = dict.fromkeys(NAMES, True)
    assert repo._partial_return_schema() is True
    connection.flags["credit_present"] = False
    with pytest.raises(PlatformError):
        repo._partial_return_schema()
    assert len(connection.calls) == 3


def test_catalog_execution_error_is_not_caught_as_legacy_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _connection = repository(dict.fromkeys(NAMES, False), monkeypatch)
    def fail(*args: Any) -> Any:
        raise RuntimeError("Synthetic catalog refusal")
    monkeypatch.setattr(repo.connection, "execute", fail)
    with pytest.raises(RuntimeError, match="catalog refusal"):
        repo._partial_return_schema()
