from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.db.exporter import DBBridgeError
from reconforge.db.importers import import_review_state
from reconforge.evidence.binder import generate_evidence_binder
from reconforge.io import generated as generated_module
from reconforge.io.generated import GeneratedArtifactError
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.review import state as state_module
from reconforge.review.state import (
    REVIEW_STATE_INGRESS_PROFILE,
    REVIEW_STATE_JSON_POLICY,
    load_review_state,
)
from reconforge.studio.app import create_studio_app

runner = CliRunner()


def test_review_state_uses_named_bounded_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "review_state.json"
    path.write_text('{"version":1,"entries":{}}', encoding="utf-8")
    captured: dict[str, object] = {}
    original = state_module.read_generated_json_document

    def recording_reader(source: Path, **kwargs: object):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return original(source, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(state_module, "read_generated_json_document", recording_reader)

    assert load_review_state(path) == {}
    assert captured == {
        "policy": REVIEW_STATE_JSON_POLICY,
        "profile_id": REVIEW_STATE_INGRESS_PROFILE,
    }


def test_review_state_retains_legacy_direct_map_and_entry_coercion(tmp_path: Path) -> None:
    path = tmp_path / "review_state.json"
    path.write_text(
        """{
          "EXC-1": {"status": "unknown", "reviewer": 7, "certification_status": "unknown"},
          "EXC-2": "ignored",
          "  ": {"status": "Resolved"}
        }""",
        encoding="utf-8",
    )

    assert load_review_state(path) == {
        "EXC-1": {
            "exception_id": "EXC-1",
            "status": "New",
            "reviewer": "7",
            "certification_status": "Draft",
        },
    }


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b'{"entries":{},"entries":{}}', "json_duplicate_key"),
        (b'{"entries":{"EXC-1":{"score":NaN}}}', "document_non_finite_number"),
        (b"{bad json", "json_structure_invalid"),
        (b"\xff", "document_encoding_invalid"),
        (b"[]", "generated_json_object_required"),
    ],
)
def test_review_state_rejects_hostile_json(tmp_path: Path, raw: bytes, code: str) -> None:
    path = tmp_path / "review_state.json"
    path.write_bytes(raw)

    with pytest.raises(GeneratedArtifactError) as captured:
        load_review_state(path)

    assert captured.value.code == code
    assert str(path) not in str(captured.value)


def test_review_state_enforces_runtime_resource_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "review_state.json"
    path.write_text('{"entries":{}}', encoding="utf-8")
    monkeypatch.setattr(
        state_module,
        "REVIEW_STATE_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=4),
    )

    with pytest.raises(GeneratedArtifactError) as captured:
        load_review_state(path)

    assert captured.value.code == "generated_file_size_limit"


def test_review_state_rejects_change_during_parse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "review_state.json"
    path.write_text('{"entries":{}}', encoding="utf-8")
    original = generated_module.read_json_document

    def mutate_after_parse(*args: object, **kwargs: object) -> object:
        payload = original(*args, **kwargs)  # type: ignore[arg-type]
        path.write_text('{"entries":{"EXC-2":{}}}', encoding="utf-8")
        return payload

    monkeypatch.setattr(generated_module, "read_json_document", mutate_after_parse)

    with pytest.raises(GeneratedArtifactError) as captured:
        load_review_state(path)

    assert captured.value.code == "generated_file_changed"


def test_review_set_status_refuses_unsafe_existing_state_without_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "review_state.json"
    original = b'{"entries":{},"entries":{"EXC-1":{}}}'
    path.write_bytes(original)

    result = runner.invoke(
        app,
        [
            "review",
            "set-status",
            "--exception-id",
            "EXC-1",
            "--status",
            "Resolved",
            "--input",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "Review state failed safety validation." in result.output
    assert str(path) not in result.output
    assert path.read_bytes() == original


def test_review_list_refuses_unsafe_state_with_safe_error(tmp_path: Path) -> None:
    path = tmp_path / "review_state.json"
    path.write_text('{"entries":{},"entries":{}}', encoding="utf-8")

    result = runner.invoke(app, ["review", "list", "--input", str(tmp_path)])

    assert result.exit_code == 1
    assert "Generated report input failed safety validation." in result.output
    assert str(path) not in result.output


def test_studio_surfaces_unsafe_state_and_does_not_replace_it(tmp_path: Path) -> None:
    path = tmp_path / "review_state.json"
    original = b'{"entries":{},"entries":{}}'
    path.write_bytes(original)
    client = TestClient(create_studio_app("examples/sample_data", tmp_path))

    response = client.get("/exceptions")

    assert response.status_code == 200
    assert "Review state failed safety validation. The file was not loaded." in response.text
    assert str(path) not in response.text
    assert path.read_bytes() == original


def test_db_import_wraps_unsafe_review_state_without_database_mutation(tmp_path: Path) -> None:
    path = tmp_path / "review_state.json"
    path.write_text('{"entries":{},"entries":{}}', encoding="utf-8")
    database = tmp_path / "review.db"

    with pytest.raises(DBBridgeError, match="Unable to import review state records"):
        import_review_state(database, path)

    assert not database.exists()


def test_evidence_binder_refuses_unsafe_review_state(tmp_path: Path) -> None:
    input_path = tmp_path / "input"
    input_path.mkdir()
    input_path.joinpath("review_state.json").write_text(
        '{"entries":{},"entries":{}}',
        encoding="utf-8",
    )

    with pytest.raises(GeneratedArtifactError):
        generate_evidence_binder(input_path, tmp_path / "evidence")


def test_review_state_loader_has_no_direct_json_or_text_reader() -> None:
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "reconforge" / "review" / "state.py").read_text(encoding="utf-8"))
    loader = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "load_review_state"
    )
    calls = {ast.unparse(node.func) for node in ast.walk(loader) if isinstance(node, ast.Call)}

    assert not ({"json.load", "json.loads"} & calls)
    assert not any(name.endswith(".read_text") for name in calls)
