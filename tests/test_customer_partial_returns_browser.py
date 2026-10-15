"""Custody boundaries only; mocked captures never count as native financial proof."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from reconforge.infrastructure.postgres import _HybridPostgresRow
from tests import customer_partial_returns_browser as observer


def empty_tables() -> dict[str, list[str]]:
    return {name: [] for name in observer.TABLES}


def runtime() -> Any:
    return SimpleNamespace(tenant="synthetic-tenant", factory=SimpleNamespace(settings=SimpleNamespace(dsn="synthetic-dsn")))


def last(version: int) -> dict[str, Any] | None:
    return {"phase": 2, "plan_id": "plan-" + str(version), "plan_digest": "d" * 64} if version else None


def capture(root: Path, monkeypatch: pytest.MonkeyPatch, version: int, *, tables: dict[str, list[str]] | None = None) -> dict[str, Any]:
    monkeypatch.setattr(observer, "_snapshot", lambda *_: (version, tables if tables is not None else empty_tables(), last(version)))
    return observer.capture_customer_partial_returns(runtime(), "original-stock", root,
        posted_plan_id="plan-" + str(version) if version else None, plan_digest="d" * 64 if version else None)


def test_complete_atomic_originals_bind_all_versions_and_typed_original_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tables = empty_tables()
    tables["finance_entry_lines"] = ['{"debit_minor": 9007199254740993, "quantity": 1.25}']
    for number in range(9):
        proof = capture(tmp_path, monkeypatch, number, tables=tables)
        assert proof["history_version"] == number and proof["raw_rows_published"] is False
    packet = observer.assemble_customer_partial_return_inputs(tmp_path, tenant="synthetic-tenant", source_order_id="original-stock")
    assert len(packet["captures"]) == 9 and set(packet["captures"][0]) == set(observer.TABLES)
    assert packet["captures"][-1]["finance_entry_lines"] == tables["finance_entry_lines"]
    assert not list(tmp_path.glob(".pending-*"))
    # Opaque PG NUMERIC row text is never decoded into binary float or rounded.
    assert b'9007199254740993' in (tmp_path / observer.PACKET_NAME).read_bytes()


def test_exact_committed_retry_does_not_append_or_rewrite_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture(tmp_path, monkeypatch, 0)
    first = capture(tmp_path, monkeypatch, 1)
    original = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.iterdir()}
    assert capture(tmp_path, monkeypatch, 1) == first
    assert {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.iterdir()} == original


def test_retry_original_drift_is_refused_without_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "accepted-originals"
    capture(root, monkeypatch, 0)
    capture(root, monkeypatch, 1)
    before = (root / "committed-capture-1.json").read_bytes()
    drift = empty_tables()
    drift["finance_entry_lines"] = ['{"changed": true}']
    with pytest.raises(observer.PartialBrowserCustodyError):
        capture(root, monkeypatch, 1, tables=drift)
    assert (root / "committed-capture-1.json").read_bytes() == before
    files = list((tmp_path / observer.REFUSED_OBSERVATIONS).iterdir())
    assert len(files) == 1 and files[0].name.startswith("refused-observation-")
    diagnostic = observer.parse_json_document(files[0].read_text(), reject_fractional_numbers=True)
    assert isinstance(diagnostic, dict)
    assert diagnostic["schema_version"] == "customer-partial-return-refused-observation-v1"
    assert diagnostic["candidate"]["tables"] == drift and len(diagnostic["candidate"]["tables"]) == 78
    assert diagnostic["retained_original_sha256"] == observer.hashlib.sha256(before).hexdigest()
    assert diagnostic["retained_original_bytes"] == len(before)
    assert [path.name for path in observer._capture_files(root)] == ["committed-capture-0.json", "committed-capture-1.json"]


@pytest.mark.parametrize("version", [1, 2, 8])
def test_initial_capture_cannot_be_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: int) -> None:
    with pytest.raises(observer.PartialBrowserCustodyError):
        capture(tmp_path, monkeypatch, version)
    assert not list(tmp_path.iterdir())


def test_wrong_reply_or_unposted_plan_cannot_be_bound_as_a_committed_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture(tmp_path, monkeypatch, 0)
    for row in ({"phase": 1, "plan_id": "plan-1", "plan_digest": "d" * 64},
                {"phase": 2, "plan_id": "foreign", "plan_digest": "d" * 64},
                {"phase": 2, "plan_id": "plan-1", "plan_digest": "e" * 64}):
        monkeypatch.setattr(observer, "_snapshot", lambda *_, row=row: (1, empty_tables(), row))
        with pytest.raises(observer.PartialBrowserCustodyError):
            observer.capture_customer_partial_returns(runtime(), "original-stock", tmp_path, posted_plan_id="plan-1", plan_digest="d" * 64)
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("name", ["unknown.json", "committed-capture-9.json", "committed-capture-00.json", ".pending-original"])
def test_unknown_or_incomplete_storage_is_quarantined(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_bytes(b"private-original")
    with pytest.raises(observer.PartialBrowserCustodyError):
        observer._capture_files(tmp_path)


def test_prior_capture_tenant_or_source_swap_is_refused_before_observation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture(tmp_path, monkeypatch, 0)
    monkeypatch.setattr(observer, "_snapshot", lambda *_: pytest.fail("No database observation after prior identity refusal"))
    with pytest.raises(observer.PartialBrowserCustodyError):
        observer.capture_customer_partial_returns(runtime(), "another-source", tmp_path)


@pytest.mark.parametrize("change", ["extra", "missing_table", "extra_table", "duplicate_rows", "wrong_order", "boolean_version", "fractional_version", "duplicate_key"])
def test_exact_capture_schema_rejects_malformed_or_opaque_extras(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    capture(tmp_path, monkeypatch, 0)
    path = tmp_path / "committed-capture-0.json"
    value = observer._load_capture(path)
    if change == "extra":
        value["password"] = "never-publish"
    elif change == "missing_table":
        value["tables"].pop(observer.TABLES[0])
    elif change == "extra_table":
        value["tables"]["unowned_table"] = []
    elif change == "duplicate_rows":
        value["tables"][observer.TABLES[0]] = ["same", "same"]
    elif change == "wrong_order":
        value["tables"][observer.TABLES[0]] = ["z", "a"]
    elif change == "boolean_version":
        value["history_version"] = False
    elif change == "fractional_version":
        value["history_version"] = 0.0
    original = observer._bytes(value, observer.MAX_CAPTURE_BYTES)
    if change == "duplicate_key":
        original = original.replace(b'"history_version":0', b'"history_version":0,"history_version":0')
    path.write_bytes(original)
    with pytest.raises(ValueError):
        observer._load_capture(path)


def test_missing_history_capture_or_oversized_original_refuses_assembly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture(tmp_path, monkeypatch, 0)
    with pytest.raises(observer.PartialBrowserCustodyError):
        observer.assemble_customer_partial_return_inputs(tmp_path, tenant="synthetic-tenant", source_order_id="original-stock")
    path = tmp_path / "committed-capture-0.json"
    path.write_bytes(b" " * (observer.MAX_CAPTURE_BYTES + 1))
    with pytest.raises(observer.PartialBrowserCustodyError):
        observer._load_capture(path)


@pytest.mark.parametrize("kind", ["is_symlink", "is_junction"])
def test_link_classifications_refuse_owned_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    target = tmp_path / "private"
    monkeypatch.setattr(Path, kind, lambda path: path == target, raising=False)
    with pytest.raises(observer.PartialBrowserCustodyError):
        observer._storage(target)


def test_atomic_destination_race_cannot_replace_an_existing_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "immutable.json"
    def race_link(_source: Any, destination: Path, **_kwargs: Any) -> None:
        destination.write_bytes(b"retained-original")
        raise FileExistsError
    monkeypatch.setattr(observer.os, "link", race_link)
    with pytest.raises(observer.PartialBrowserCustodyError):
        observer._retain(path, b"new-candidate", same_allowed=True)
    assert path.read_bytes() == b"retained-original" and not list(tmp_path.glob(".pending-*"))


def test_restore_verifier_preserves_stable_proof_and_exact_final_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for version in range(9):
        capture(tmp_path, monkeypatch, version)
    monkeypatch.setattr(observer, "customer_partial_returns_browser_source", lambda _: "original-stock")
    main = runtime()
    restored = deepcopy(main)
    restored.factory.settings.dsn = "synthetic-restored-dsn"
    first = observer.verify_customer_partial_returns_browser(main, custody_root=tmp_path, original_app_dsn="synthetic-dsn")
    assert not (tmp_path / observer.RESTORE_NAME).exists()
    second = observer.verify_customer_partial_returns_browser(restored, custody_root=tmp_path, original_app_dsn="synthetic-dsn")
    assert first == second and (tmp_path / observer.RESTORE_NAME).is_file()
    original = (tmp_path / observer.RESTORE_NAME).read_bytes()
    observer.verify_customer_partial_returns_browser(restored, custody_root=tmp_path, original_app_dsn="synthetic-dsn")
    assert (tmp_path / observer.RESTORE_NAME).read_bytes() == original
    drift = empty_tables()
    drift[observer.TABLES[0]] = ['{"changed":1}']
    monkeypatch.setattr(observer, "_snapshot", lambda *_: (8, drift, last(8)))
    with pytest.raises(observer.PartialBrowserCustodyError):
        observer.verify_customer_partial_returns_browser(restored, custody_root=tmp_path, original_app_dsn="synthetic-dsn")
    assert (tmp_path / observer.RESTORE_NAME).read_bytes() == original


@pytest.mark.parametrize("history_version", [0, 1])
def test_real_driver_row_contract_supports_normal_flags_and_source_locks_without_dict_methods(history_version: int) -> None:
    statements: list[str] = []
    class Cursor:
        def __init__(self, rows: list[Any]) -> None:
            self.rows = rows
        def fetchone(self) -> Any:
            return self.rows[0] if self.rows else None
        def fetchall(self) -> list[Any]:
            return self.rows
    class Connection:
        def execute(self, statement: Any, _args: Any = ()) -> Cursor:
            query = statement if isinstance(statement, str) else statement.as_string()
            statements.append(query)
            if query.startswith("SELECT rolsuper"):
                return Cursor([_HybridPostgresRow(("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolreplication"), (False,) * 5)])
            if query.startswith("SELECT count(*) n FROM pg_class"):
                return Cursor([_HybridPostgresRow(("n",), (len(observer.TABLES),))])
            if query.startswith("SELECT customer_id,invoice_id"):
                return Cursor([_HybridPostgresRow(("customer_id", "invoice_id"), ("customer", "invoice"))])
            if query.startswith("SELECT h.sequence") and history_version:
                return Cursor([_HybridPostgresRow(("sequence", "plan_id", "plan_digest", "phase"), (1, "plan-1", "d" * 64, 2))])
            if "FOR SHARE" in query:
                return Cursor([_HybridPostgresRow(("id",), ("locked",))])
            return Cursor([])
    @contextmanager
    def actor(_name: str) -> Any:
        yield Connection(), None, None
    fixture = runtime()
    fixture.actor = actor
    version, tables, current = observer._snapshot(fixture, "original-stock")
    assert version == history_version and tables == empty_tables()
    assert current == ({"sequence": 1, "plan_id": "plan-1", "plan_digest": "d" * 64, "phase": 2} if history_version else None)
    assert len([query for query in statements if "FOR SHARE" in query]) == 3
    assert len([query for query in statements if query.startswith("SELECT to_jsonb")]) == 78
