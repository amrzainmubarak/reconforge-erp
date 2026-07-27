from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path

import pytest

from reconforge import cli
from reconforge.io import records as record_module
from reconforge.io.records import (
    BUSINESS_RECORD_CSV_POLICY,
    BUSINESS_RECORD_INGRESS_PROFILE,
    BUSINESS_RECORD_JSON_POLICY,
    RecordIngressError,
    read_business_record_document,
    read_json_record_document,
)
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.platform.common import PlatformError, read_local_records


def _assert_code(captured: pytest.ExceptionInfo[RecordIngressError], code: str) -> None:
    assert captured.value.code == code
    assert str(captured.value) == f"Business record input rejected ({code})."


def test_json_records_preserve_fractional_lexemes_and_bind_provenance(tmp_path: Path) -> None:
    path = tmp_path / "records.json"
    raw = b'[{"amount":75.2500,"rate":1e-7,"count":2}]'
    path.write_bytes(raw)

    document = read_business_record_document(path)

    assert document.records == [{"amount": "75.2500", "rate": "1e-7", "count": 2}]
    assert document.checksum_sha256 == sha256(raw).hexdigest()
    assert document.size_bytes == len(raw)
    assert document.profile_id == BUSINESS_RECORD_INGRESS_PROFILE
    assert document.format == "json"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b'{"records":[],"rows":[]}', "json_record_envelope_ambiguous"),
        (b'{"records":[1]}', "json_record_not_object"),
        (b'{"records":{}}', "json_record_collection_required"),
        (b'{"amount":NaN}', "document_non_finite_number"),
        (b'{"amount":1,"amount":2}', "json_duplicate_key"),
        (b"\xff", "document_encoding_invalid"),
        (b"", "record_file_empty"),
    ],
)
def test_json_records_reject_ambiguous_or_hostile_inputs(
    tmp_path: Path,
    raw: bytes,
    code: str,
) -> None:
    path = tmp_path / "records.json"
    path.write_bytes(raw)

    with pytest.raises(RecordIngressError) as captured:
        read_business_record_document(path)

    _assert_code(captured, code)


def test_generic_json_reader_preserves_single_object_compatibility(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    path.write_text('{"id":"A","amount":2.500}', encoding="utf-8")

    resolved, records = read_local_records(path)

    assert resolved == path.resolve()
    assert records == [{"id": "A", "amount": "2.500"}]


def test_specialized_json_reader_requires_its_declared_envelope(tmp_path: Path) -> None:
    path = tmp_path / "lines.json"
    path.write_text('{"rows":[]}', encoding="utf-8")

    with pytest.raises(RecordIngressError) as captured:
        read_json_record_document(path, envelope_keys=("lines",))

    _assert_code(captured, "json_record_collection_required")


def test_csv_records_are_strict_and_bound_to_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    raw = b"id,amount\r\nA,2.500\r\n"
    path.write_bytes(raw)

    document = read_business_record_document(path)

    assert document.records == [{"id": "A", "amount": "2.500"}]
    assert document.checksum_sha256 == sha256(raw).hexdigest()
    assert document.size_bytes == len(raw)
    assert document.format == "csv"


@pytest.mark.parametrize("header", ["id,id\nA,B\n", "id, \nA,B\n"])
def test_csv_records_reject_ambiguous_headers(tmp_path: Path, header: str) -> None:
    path = tmp_path / "records.csv"
    path.write_text(header, encoding="utf-8")

    with pytest.raises(RecordIngressError) as captured:
        read_business_record_document(path)

    _assert_code(captured, "csv_header_ambiguous")


def test_record_budget_rejects_before_returning_partial_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "records.json"
    path.write_text('[{"id":1},{"id":2}]', encoding="utf-8")
    monkeypatch.setattr(record_module, "BUSINESS_RECORD_MAX_RECORDS", 1)

    with pytest.raises(RecordIngressError) as captured:
        read_business_record_document(path)

    _assert_code(captured, "record_count_limit")


def test_json_policy_file_limit_is_used_by_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "records.json"
    path.write_text('[{"id":1}]', encoding="utf-8")
    monkeypatch.setattr(
        record_module,
        "BUSINESS_RECORD_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=4),
    )

    with pytest.raises(RecordIngressError) as captured:
        read_business_record_document(path)

    _assert_code(captured, "record_file_size_limit")


def test_changed_file_is_rejected_after_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "records.json"
    path.write_text('[{"id":1}]', encoding="utf-8")
    original = record_module._bounded_fingerprint
    calls = 0

    def changed(candidate: Path, *, max_file_bytes: int) -> tuple[str, int]:
        nonlocal calls
        calls += 1
        digest, size = original(candidate, max_file_bytes=max_file_bytes)
        return ("0" * 64, size) if calls == 2 else (digest, size)

    monkeypatch.setattr(record_module, "_bounded_fingerprint", changed)

    with pytest.raises(RecordIngressError) as captured:
        read_business_record_document(path)

    _assert_code(captured, "record_file_changed")


def test_reparse_points_are_rejected_without_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "records.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(record_module, "_path_is_reparse", lambda _path: True)

    with pytest.raises(RecordIngressError) as captured:
        read_business_record_document(path)

    _assert_code(captured, "record_file_not_regular")


def test_cli_financial_line_readers_preserve_exact_lexemes(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text('{"lines":[{"account_code":"1000","debit":75.2500,"credit":0}]}', encoding="utf-8")
    inventory = tmp_path / "inventory.json"
    inventory.write_text('{"lines":[{"item_code":"SKU","quantity":2.500}]}', encoding="utf-8")
    receivables = tmp_path / "receivables.json"
    receivables.write_text('{"lines":[{"quantity":1e-3,"unit_price_minor":1,"line_total_minor":1}]}', encoding="utf-8")

    assert cli._ledger_lines_from_json(ledger)[0]["debit"] == "75.2500"
    assert cli._inventory_lines_from_json(inventory)[0]["quantity"] == "2.500"
    assert cli._receivables_json_records(receivables, key="lines")[0]["quantity"] == "1e-3"


def test_cli_specialized_reader_keeps_safe_shape_error(tmp_path: Path) -> None:
    path = tmp_path / "lines.json"
    path.write_text('{"lines":[1]}', encoding="utf-8")

    with pytest.raises(PlatformError, match="Each ledger line in JSON must be an object"):
        cli._ledger_lines_from_json(path)


def test_business_record_policy_contract_is_explicit() -> None:
    assert BUSINESS_RECORD_JSON_POLICY.max_file_bytes == 64 * 1024 * 1024
    assert BUSINESS_RECORD_JSON_POLICY.max_nodes == 2_000_000
    assert BUSINESS_RECORD_JSON_POLICY.max_depth == 32
    assert BUSINESS_RECORD_JSON_POLICY.max_collection_items == 250_000
    assert BUSINESS_RECORD_CSV_POLICY.max_rows == 250_000
    assert BUSINESS_RECORD_CSV_POLICY.max_columns == 512
    assert BUSINESS_RECORD_CSV_POLICY.max_cells == 10_000_000


def test_legacy_business_entrypoints_delegate_to_central_reader() -> None:
    root = Path(__file__).resolve().parents[1]
    targets = {
        "reconforge/platform/common.py": {"read_local_records"},
        "reconforge/cli.py": {
            "_ledger_lines_from_json",
            "_inventory_lines_from_json",
            "_receivables_json_records",
        },
    }
    forbidden: list[str] = []
    for relative, functions in targets.items():
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in functions:
                continue
            for call in (child for child in ast.walk(node) if isinstance(child, ast.Call)):
                name = ast.unparse(call.func)
                if name in {"json.load", "json.loads", "csv.DictReader"} or name.endswith(".read_text"):
                    forbidden.append(f"{relative}:{node.name}:{name}")
    assert forbidden == []
