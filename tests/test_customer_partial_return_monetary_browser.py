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
    def snapshot(_runtime, _source, *, index):
        if type(index) is not int or not 0 <= index < 10:
            raise ValueError("Invalid synthetic index")
        return {"capture": index, "tables": deepcopy(retained)}, browser.HISTORY_VERSIONS[index]
    monkeypatch.setattr(browser, "_snapshot", snapshot)


def root(tmp_path: Path, case: str = "foreign") -> Path:
    return tmp_path / browser.FAMILY / case


def original_cycle(monkeypatch, tmp_path):
    data = tables()
    stage(monkeypatch, data)
    custody = root(tmp_path)
    for index in range(10):
        result = browser.capture_monetary_browser(runtime(), "source", custody, case="foreign", index=index)
        assert result["tables"] == 91 and result["independent_financial_and_audit_verification_required"] is True
    return custody, data


def test_exact_ten_captures_use_91_tables_without_confusing_capture_and_history(monkeypatch, tmp_path):
    custody, _data = original_cycle(monkeypatch, tmp_path)
    packet = decode_packet((custody / browser.PACKET).read_bytes())
    assert packet.tenant_id == "tenant" and packet.source_order_id == "source" and len(packet.captures) == 10
    assert [capture.index for capture in packet.captures] == list(range(10))
    assert browser.HISTORY_VERSIONS == (0, 0, 0, 1, 2, 3, 4, 5, 6, 7)
    assert all({name for name, _rows in capture.raw_tables} == set(TABLES) for capture in packet.captures)


@pytest.mark.parametrize("name", ["arbitrary.json", "committed-capture-10.json", "source.sql", "committed-capture-01.json"])
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


@pytest.mark.parametrize("index", [True, False, -1, 10, "0", 1.0])
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
    baseline = (custody / "committed-capture-9.json").read_bytes()
    data["finance_entry_lines"].append('{"id":"changed","tenant_id":"tenant","debit_minor":1}')
    stage(monkeypatch, data)
    with pytest.raises(ValueError):
        browser.capture_monetary_browser(runtime(), "source", custody, case="foreign", index=9, observation="ScopeRefusal", refusal={"operation": "ReadSource", "status": 403, "code": "entity_scope_denied"})
    failed = custody.parent.parent / browser.REFUSED / "foreign"
    assert len(list(failed.glob("refused-*.json"))) == 1
    assert (custody / "committed-capture-9.json").read_bytes() == baseline
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
        browser.capture_monetary_browser(runtime(), "source", custody, case="foreign", index=9, observation="ScopeRefusal", refusal=refusal)


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
    for kind, name in browser.KINDS.items():
        index = 7 if kind == "RetainedReplay" else 9
        value = {"schema_version": browser.OBSERVATION_SCHEMA, "kind": kind, "tenant_id": "tenant", "source_order_id": "source", "capture": index,
                 "history_version": browser.HISTORY_VERSIONS[index], "plan_id": "CRF3-" + "1" * 32 if kind == "RetainedReplay" else None,
                 "plan_digest": "a" * 64 if kind == "RetainedReplay" else None, "tables": data,
                 "refusal": {"operation": "ReadSource", "status": 403, "code": "entity_scope_denied"} if kind == "ScopeRefusal" else None}
        (folder / name).write_bytes(_bytes(value, browser.MAX_CAPTURE_BYTES + 4096))
    first = browser.verify_seeded_monetary_browser(runtime("synthetic-restored"), custody_root=custody, case="foreign", original_app_dsn="synthetic-original")
    second = browser.verify_seeded_monetary_browser(runtime("synthetic-restored"), custody_root=custody, case="foreign", original_app_dsn="synthetic-original")
    assert first == second and len(first["tables"]) == 91 and first["independent_financial_and_audit_verification_required"] is True
    assert (custody / browser.RESTORE).exists()
    data["ar_invoices"] = ['{"id":"changed","tenant_id":"tenant"}']
    stage(monkeypatch, data)
    with pytest.raises(ValueError):
        browser.verify_seeded_monetary_browser(runtime("synthetic-restored"), custody_root=custody, case="foreign", original_app_dsn="synthetic-original")
