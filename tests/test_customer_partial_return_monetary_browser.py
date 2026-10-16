"""Custody/lock/parser tests; synthetic rows are not native financial acceptance."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests import customer_partial_return_monetary_browser as browser
from tests.customer_partial_return_monetary_posted_oracle import TABLES, decode_packet
from tests.customer_partial_returns_browser import _bytes


def tables() -> dict[str, list[str]]:
    return {name: [] for name in TABLES}


def runtime(dsn: str = "synthetic-original") -> Any:
    return SimpleNamespace(tenant="tenant", factory=SimpleNamespace(settings=SimpleNamespace(dsn=dsn)))


def stage(monkeypatch: pytest.MonkeyPatch, retained: dict[str, list[str]]) -> None:
    def snapshot(_runtime, _source, *, index, case):
        if type(index) is not int or not 0 <= index < len(browser._versions(case)):
            raise ValueError("Invalid synthetic index")
        return {"capture": index, "tables": deepcopy(retained)}, browser._versions(case)[index]
    monkeypatch.setattr(browser, "_snapshot", snapshot)


def root(tmp_path: Path, case: str = "foreign") -> Path:
    return tmp_path / browser.FAMILY / case


def refused_request() -> dict[str, Any]:
    return {"method": "POST", "route": "/api/v3/customer-partial-returns/plans", "body": {
        "command_id": "synthetic-refusal-command", "source_order_id": "source", "quantity_scaled": "4", "period_id": "period",
        "posting_date": "2026-10-15", "reason": "Actual attempted return while valuation is active", "expected_history_version": 2}}


def original_cycle(monkeypatch, tmp_path):
    data = tables()
    stage(monkeypatch, data)
    custody = root(tmp_path)
    for index in range(12):
        result = browser.capture_monetary_browser(runtime(), "source", custody, case="foreign", index=index)
        assert result["tables"] == 91 and result["independent_financial_and_audit_verification_required"] is True
    return custody, data


def test_exact_twelve_foreign_captures_use_91_tables_without_confusing_capture_and_history(monkeypatch, tmp_path):
    custody, _data = original_cycle(monkeypatch, tmp_path)
    packet = decode_packet((custody / browser.PACKET).read_bytes())
    assert packet.tenant_id == "tenant" and packet.source_order_id == "source" and len(packet.captures) == 12
    assert [capture.index for capture in packet.captures] == list(range(12))
    assert browser.HISTORY_VERSIONS == (0, 0, 0, 1, 2, 3, 4, 5, 6, 7)
    assert browser.FOREIGN_HISTORY_VERSIONS == (0, 0, 0, 1, 2, 2, 2, 3, 4, 5, 6, 7)
    assert all({name for name, _rows in capture.raw_tables} == set(TABLES) for capture in packet.captures)


@pytest.mark.parametrize("name", ["arbitrary.json", "committed-capture-12.json", "source.sql", "committed-capture-01.json"])
def test_unknown_or_noncanonical_raw_family_member_refuses_before_assembly(monkeypatch, tmp_path, name):
    custody, _data = original_cycle(monkeypatch, tmp_path)
    (custody / name).write_bytes(b"{}")
    before = (custody / browser.PACKET).read_bytes()
    with pytest.raises(ValueError):
        browser.assemble_monetary_browser(custody, case="foreign", tenant="tenant", source="source")
    assert (custody / browser.PACKET).read_bytes() == before


def test_capture_never_overwrites_or_silently_reclassifies_a_retry(monkeypatch, tmp_path):
    custody = root(tmp_path)
    stage(monkeypatch, tables())
    browser.capture_monetary_browser(runtime(), "source", custody, case="foreign", index=0)
    original = (custody / "committed-capture-0.json").read_bytes()
    with pytest.raises(ValueError):
        browser.capture_monetary_browser(runtime(), "source", custody, case="foreign", index=0)
    assert (custody / "committed-capture-0.json").read_bytes() == original
    with pytest.raises(ValueError):
        browser.capture_monetary_browser(runtime(), "source", custody, case="foreign", index=2)


@pytest.mark.parametrize("index", [True, False, -1, 12, "0", 1.0])
def test_capture_index_has_no_boolean_float_or_text_coercion(monkeypatch, tmp_path, index):
    stage(monkeypatch, tables())
    with pytest.raises(ValueError):
        browser.capture_monetary_browser(runtime(), "source", root(tmp_path), case="foreign", index=index)


@pytest.mark.parametrize("case", ["ordinary", "zero", "refund", "Foreign", "../foreign"])
def test_only_new_fixed_case_names_and_private_path_layout_are_admitted(tmp_path, case):
    with pytest.raises(ValueError):
        browser._root(root(tmp_path, case), case)


def test_all_89_business_tables_remain_exact_and_refused_candidate_is_retained(monkeypatch, tmp_path):
    custody, data = original_cycle(monkeypatch, tmp_path)
    baseline = (custody / "committed-capture-11.json").read_bytes()
    data["finance_entry_lines"].append('{"id":"changed","tenant_id":"tenant","debit_minor":1}')
    stage(monkeypatch, data)
    with pytest.raises(ValueError):
        browser.capture_monetary_browser(runtime(), "source", custody, case="foreign", index=11, observation="ScopeRefusal", refusal={"operation": "ReadSource", "status": 403, "code": "entity_scope_denied"})
    failed = custody.parent.parent / browser.REFUSED / "foreign"
    assert len(list(failed.glob("refused-*.json"))) == 1
    assert (custody / "committed-capture-11.json").read_bytes() == baseline
    assert not (custody.parent.parent / browser.OBSERVATIONS / "foreign" / "scope-refusal.json").exists()


def test_every_prior_audit_original_is_retained_even_though_independent_chain_qualification_is_separate():
    before, after = tables(), tables()
    before["domain_audit_events"] = ['{"id":"prior","tenant_id":"tenant"}']
    with pytest.raises(ValueError):
        browser._unchanged_business(before, after)
    after["domain_audit_events"] = [*before["domain_audit_events"], '{"id":"later","tenant_id":"tenant"}']
    browser._unchanged_business(before, after)


@pytest.mark.parametrize("refusal", [{"operation": "ReadSource", "status": True, "code": "denied"}, {"operation": "PostPlan", "status": 403, "code": "denied"}, {"operation": "ReadSource", "status": 403, "code": "raw\nmessage"}, {"operation": "ReadSource", "status": 403, "code": "denied", "headers": {}}])
def test_scope_refusal_is_a_closed_actual_response_receipt(monkeypatch, tmp_path, refusal):
    custody, _data = original_cycle(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        browser.capture_monetary_browser(runtime(), "source", custody, case="foreign", index=11, observation="ScopeRefusal", refusal=refusal)


class Result:
    def __init__(self, values):
        self.values = values

    def fetchall(self):
        return self.values

    def fetchone(self):
        return self.values[0] if self.values else None


def test_parent_share_lock_order_allows_absent_unrecognized_invoice_and_rechecks_source():
    class Connection:
        def __init__(self):
            self.queries = []

        def execute(self, statement, _parameters):
            query = statement if isinstance(statement, str) else statement.as_string()
            self.queries.append(query)
            assert query.lstrip().startswith("SELECT ")
            if "schema_version" in query:
                return Result([{"customer_id": "customer", "invoice_id": None, "schema_version": "stock-sales-monetary-order-v2"}])
            if "customer_id,invoice_id" in query:
                return Result([{"customer_id": "customer", "invoice_id": None}])
            return Result([{"tenant_id": "tenant", "id": "source"}])
    connection = Connection()
    browser._parents(connection, "tenant", "source")
    locks = [query for query in connection.queries if "FOR SHARE" in query]
    assert len(locks) == 3 and "ar_customers" in locks[0] and "stock_sales_orders" in locks[1] and "domain_audit_ledger_state" in locks[2]


def test_final_restore_uses_exact_91_final_observation_rows_and_stable_repeat_proof(monkeypatch, tmp_path):
    custody, data = original_cycle(monkeypatch, tmp_path)
    folder = custody.parent.parent / browser.OBSERVATIONS / "foreign"
    folder.mkdir(parents=True)
    for kind, name in browser._kinds("foreign").items():
        index = browser._observation_index("foreign", kind)
        pinned = kind in {"RetainedReplay", "ActiveValuationRefusal"}
        value = {"schema_version": browser.OBSERVATION_SCHEMA, "kind": kind, "tenant_id": "tenant", "source_order_id": "source", "capture": index,
                 "history_version": browser.FOREIGN_HISTORY_VERSIONS[index], "plan_id": ("FX1-" if kind == "ActiveValuationRefusal" else "CRF3-") + "1" * 32 if pinned else None,
                 "plan_digest": "a" * 64 if pinned else None, "tables": data,
                 "refusal": {"operation": "PrepareReturn", "status": 409, "code": "customer_partial_return_monetary_state_invalid"} if kind == "ActiveValuationRefusal" else {"operation": "ReadSource", "status": 403, "code": "entity_scope_denied"} if kind == "ScopeRefusal" else None}
        (folder / name).write_bytes(_bytes(value, browser.MAX_CAPTURE_BYTES + 4096))
    (folder / browser.REFUSED_REQUEST).write_bytes(_bytes(refused_request(), 8192))
    first = browser.verify_seeded_monetary_browser(runtime("synthetic-restored"), custody_root=custody, case="foreign", original_app_dsn="synthetic-original")
    second = browser.verify_seeded_monetary_browser(runtime("synthetic-restored"), custody_root=custody, case="foreign", original_app_dsn="synthetic-original")
    assert first == second and len(first["tables"]) == 91 and first["independent_financial_and_audit_verification_required"] is True
    assert (custody / browser.RESTORE).exists()
    data["ar_invoices"] = ['{"id":"changed","tenant_id":"tenant"}']
    stage(monkeypatch, data)
    with pytest.raises(ValueError):
        browser.verify_seeded_monetary_browser(runtime("synthetic-restored"), custody_root=custody, case="foreign", original_app_dsn="synthetic-original")


def test_identity_keeps_its_original_ten_captures_without_valuation_slots(monkeypatch, tmp_path):
    stage(monkeypatch, tables())
    custody = root(tmp_path, "identity")
    for index in range(10):
        browser.capture_monetary_browser(runtime(), "source", custody, case="identity", index=index)
    assert len(decode_packet((custody / browser.PACKET).read_bytes()).captures) == 10
    assert set(browser._kinds("identity")) == {"RetainedReplay", "ScopeRefusal", "FinalRead"}
    with pytest.raises(ValueError):
        browser._observation_index("identity", "ActiveValuationRefusal")


@pytest.mark.parametrize("change", [{"source_order_id": "other"}, {"quantity_scaled": 4}, {"quantity_scaled": "5"}, {"expected_history_version": True}, {"expected_history_version": 3}, {"allocation_policy": "override"}, {"reason": "raw\nmessage"}, {"posting_date": "2026-02-30"}])
def test_refused_active_valuation_request_has_exact_native_intent_not_caller_authority(change):
    value = refused_request()
    value["body"].update(change)
    with pytest.raises(ValueError):
        browser._request_pin(value, "source")


def test_active_valuation_request_receipt_has_no_headers_or_rewritten_route():
    browser._request_pin(refused_request(), "source")
    for change in ({"headers": {}}, {"route": "/api/v2/customer-partial-returns/plans"}, {"method": "GET"}):
        with pytest.raises(ValueError):
            browser._request_pin({**refused_request(), **change}, "source")


def test_actual_fx_plan_digest_comes_from_immutable_payload_not_an_absent_column():
    class Connection:
        def execute(self, query, parameters):
            assert "p.payload->>'plan_digest'" in query and "p.plan_digest" not in query
            assert parameters == ("tenant", "FX1-" + "1" * 32, "source")
            return Result([{"phase": 2, "digest": "a" * 64}])
    browser._plan_pin(Connection(), "tenant", "source", "FX1-" + "1" * 32, "a" * 64)
