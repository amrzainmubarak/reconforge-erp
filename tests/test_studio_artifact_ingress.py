from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.io import generated as generated_module
from reconforge.io.generated import (
    GENERATED_ARTIFACT_CSV_POLICY,
    GENERATED_ARTIFACT_INGRESS_PROFILE,
    GENERATED_ARTIFACT_JSON_POLICY,
    GeneratedArtifactError,
    read_generated_csv_document,
    read_generated_json_document,
)
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.studio.app import create_studio_app
from reconforge.studio.data import _json_payload, _read_generated_csv


def _assert_code(captured: pytest.ExceptionInfo[GeneratedArtifactError], code: str) -> None:
    assert captured.value.code == code
    assert str(captured.value) == f"Generated artifact rejected ({code})."


def test_generated_csv_preserves_studio_display_typing_and_provenance(tmp_path: Path) -> None:
    path = tmp_path / "report.csv"
    raw = b"code,label,amount\r\n001,NA,2.500\r\n"
    path.write_bytes(raw)

    document = read_generated_csv_document(path)

    assert document.frame.to_dict(orient="records") == [
        {"code": 1, "label": "NA", "amount": 2.5}
    ]
    assert document.checksum_sha256 == sha256(raw).hexdigest()
    assert document.size_bytes == len(raw)
    assert document.profile_id == GENERATED_ARTIFACT_INGRESS_PROFILE


def test_generated_json_preserves_fractional_lexemes_and_provenance(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    raw = b'{"rows":[{"amount":2.500,"rate":1e-7}],"count":1}'
    path.write_bytes(raw)

    document = read_generated_json_document(path)

    assert document.payload["rows"] == [{"amount": "2.500", "rate": "1e-7"}]
    assert document.checksum_sha256 == sha256(raw).hexdigest()
    assert document.size_bytes == len(raw)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b'{"value":1,"value":2}', "json_duplicate_key"),
        (b'{"value":NaN}', "document_non_finite_number"),
        (b"[]", "generated_json_object_required"),
        (b"\xff", "document_encoding_invalid"),
        (b"", "generated_file_empty"),
    ],
)
def test_generated_json_rejects_ambiguous_or_hostile_inputs(
    tmp_path: Path,
    raw: bytes,
    code: str,
) -> None:
    path = tmp_path / "report.json"
    path.write_bytes(raw)

    with pytest.raises(GeneratedArtifactError) as captured:
        read_generated_json_document(path)

    _assert_code(captured, code)


@pytest.mark.parametrize("raw", [b"id,id\n1,2\n", b"id, \n1,2\n"])
def test_generated_csv_rejects_ambiguous_headers(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "report.csv"
    path.write_bytes(raw)

    with pytest.raises(GeneratedArtifactError) as captured:
        read_generated_csv_document(path)

    _assert_code(captured, "generated_csv_header_ambiguous")


def test_generated_csv_rejects_invalid_shape_and_encoding(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.csv"
    malformed.write_text("a,b\n1\n", encoding="utf-8")
    invalid = tmp_path / "invalid.csv"
    invalid.write_bytes(b"a\n\xff\n")

    with pytest.raises(GeneratedArtifactError) as malformed_error:
        read_generated_csv_document(malformed)
    with pytest.raises(GeneratedArtifactError) as invalid_error:
        read_generated_csv_document(invalid)

    _assert_code(malformed_error, "csv_shape_invalid")
    _assert_code(invalid_error, "csv_structure_invalid")


def test_generated_json_uses_profile_file_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "report.json"
    path.write_text('{"rows":[]}', encoding="utf-8")
    monkeypatch.setattr(
        generated_module,
        "GENERATED_ARTIFACT_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=4),
    )

    with pytest.raises(GeneratedArtifactError) as captured:
        read_generated_json_document(path)

    _assert_code(captured, "generated_file_size_limit")


@pytest.mark.parametrize("suffix", [".csv", ".json"])
def test_generated_artifact_change_is_rejected_after_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    path = tmp_path / f"report{suffix}"
    path.write_text("id\n1\n" if suffix == ".csv" else '{"id":1}', encoding="utf-8")
    original = generated_module._bounded_fingerprint
    calls = 0

    def changed(candidate: Path, *, max_file_bytes: int) -> tuple[str, int]:
        nonlocal calls
        calls += 1
        digest, size = original(candidate, max_file_bytes=max_file_bytes)
        return ("0" * 64, size) if calls == 2 else (digest, size)

    monkeypatch.setattr(generated_module, "_bounded_fingerprint", changed)

    with pytest.raises(GeneratedArtifactError) as captured:
        (
            read_generated_csv_document(path)
            if suffix == ".csv"
            else read_generated_json_document(path)
        )

    _assert_code(captured, "generated_file_changed")


def test_generated_artifact_reparse_is_rejected_without_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "report.csv"
    path.write_text("id\n1\n", encoding="utf-8")
    monkeypatch.setattr(generated_module, "_path_is_reparse", lambda _path: True)

    with pytest.raises(GeneratedArtifactError) as captured:
        read_generated_csv_document(path)

    _assert_code(captured, "generated_file_not_regular")


def test_studio_csv_helper_accepts_valid_optional_companion(tmp_path: Path) -> None:
    csv_path = tmp_path / "report.csv"
    csv_path.write_text("id,value\nA,2\n", encoding="utf-8")
    companion = tmp_path / "report.json"
    companion.write_text('{"rows":[{"id":"A","value":2}]}', encoding="utf-8")

    frame = _read_generated_csv(
        csv_path,
        companion_path=companion,
        collection_key="rows",
    )

    assert frame.to_dict(orient="records") == [{"id": "A", "value": 2}]


@pytest.mark.parametrize(
    "payload",
    [
        '{"rows":[]}',
        '{"rows":[{"missing":"A"}]}',
        '{"rows":{}}',
        '{"rows":[1]}',
        '{"rows":[],"rows":[{}]}',
    ],
)
def test_studio_csv_helper_refuses_invalid_or_inconsistent_companion(
    tmp_path: Path,
    payload: str,
) -> None:
    csv_path = tmp_path / "report.csv"
    csv_path.write_text("id,value\nA,2\n", encoding="utf-8")
    companion = tmp_path / "report.json"
    companion.write_text(payload, encoding="utf-8")

    frame = _read_generated_csv(
        csv_path,
        companion_path=companion,
        collection_key="rows",
    )

    assert frame.empty


def test_studio_helpers_keep_missing_and_invalid_artifacts_safe(tmp_path: Path) -> None:
    missing_csv = tmp_path / "missing.csv"
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text('{"x":NaN}', encoding="utf-8")

    assert _read_generated_csv(missing_csv).empty
    assert _json_payload(invalid_json) == {}


def test_studio_route_returns_safe_empty_state_for_hostile_generated_csv(tmp_path: Path) -> None:
    target = tmp_path / "control_matrix"
    target.mkdir()
    target.joinpath("control_matrix.csv").write_text("id,id\nA,B\n", encoding="utf-8")
    client = TestClient(create_studio_app("examples/sample_data", tmp_path))

    response = client.get("/control-matrix")

    assert response.status_code == 200
    assert "No control matrix has been generated yet" in response.text
    assert str(tmp_path) not in response.text


def test_generated_artifact_policy_contract_is_explicit() -> None:
    assert GENERATED_ARTIFACT_CSV_POLICY.max_file_bytes == 64 * 1024 * 1024
    assert GENERATED_ARTIFACT_CSV_POLICY.max_rows == 250_000
    assert GENERATED_ARTIFACT_CSV_POLICY.max_columns == 512
    assert GENERATED_ARTIFACT_CSV_POLICY.max_cells == 10_000_000
    assert GENERATED_ARTIFACT_JSON_POLICY.max_nodes == 1_000_000
    assert GENERATED_ARTIFACT_JSON_POLICY.max_depth == 64
    assert GENERATED_ARTIFACT_JSON_POLICY.max_collection_items == 250_000


def test_studio_entrypoints_have_no_direct_dataframe_or_json_parser() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden: list[str] = []
    for relative in ("reconforge/studio/app.py", "reconforge/studio/data.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = ast.unparse(call.func)
            if name in {"pd.read_csv", "json.load", "json.loads"} or name.endswith(".read_text"):
                forbidden.append(f"{relative}:{name}")
    assert forbidden == []
