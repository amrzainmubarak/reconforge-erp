from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.ai import summaries as summaries_module
from reconforge.ai.summaries import explain_exception_file
from reconforge.cli import app
from reconforge.dashboard.app import _load_json
from reconforge.enterprise_demo import _read_records
from reconforge.io import generated as generated_module
from reconforge.io.generated import (
    GeneratedArtifactError,
    read_generated_json_value_document,
)
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.periods import read_period_comparison
from reconforge.rules.engine import read_rule_results
from reconforge.studio import demo_bridge as demo_bridge_module
from reconforge.studio.demo_bridge import _read_object

runner = CliRunner()
JsonReader = Callable[[Path], object]


def test_generated_json_value_document_preserves_root_list_and_exact_numbers(tmp_path: Path) -> None:
    path = tmp_path / "records.json"
    path.write_text('[{"amount":2.500,"id":"001"}]', encoding="utf-8")

    document = read_generated_json_value_document(path, profile_id="test-json-value-v1")

    assert document.payload == [{"amount": "2.500", "id": "001"}]
    assert document.profile_id == "test-json-value-v1"
    assert document.size_bytes == len(path.read_bytes())


def test_generated_json_value_document_rejects_change_during_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "records.json"
    path.write_text("[]", encoding="utf-8")
    original = generated_module.read_json_document

    def mutate_after_parse(*args: object, **kwargs: object) -> object:
        payload = original(*args, **kwargs)  # type: ignore[arg-type]
        path.write_text("[{}]", encoding="utf-8")
        return payload

    monkeypatch.setattr(generated_module, "read_json_document", mutate_after_parse)

    with pytest.raises(GeneratedArtifactError) as captured:
        read_generated_json_value_document(path)

    assert captured.value.code == "generated_file_changed"


def test_migrated_json_readers_preserve_valid_compatibility_shapes(tmp_path: Path) -> None:
    ai_path = tmp_path / "ai.json"
    ai_path.write_text('[{"exception_id":"EXC-1","risk_score":75}]', encoding="utf-8")
    assert "EXC-1" in explain_exception_file(ai_path, "EXC-1")

    dashboard_path = tmp_path / "management_pack.json"
    dashboard_path.write_text('{"executive_summary":[]}', encoding="utf-8")
    assert _load_json(dashboard_path) == {"executive_summary": []}

    enterprise_path = tmp_path / "enterprise.json"
    enterprise_path.write_text('{"records":[{"id":"1"},null]}', encoding="utf-8")
    assert _read_records(enterprise_path) == [{"id": "1"}]

    period_path = tmp_path / "period.json"
    period_path.write_text('{"summary":[]}', encoding="utf-8")
    assert read_period_comparison(period_path).verification_status == "legacy-unverified"

    rule_path = tmp_path / "rules.json"
    rule_path.write_text('{"results":[]}', encoding="utf-8")
    assert read_rule_results(rule_path).verification_status == "legacy-unverified"

    studio_path = tmp_path / "studio.json"
    studio_path.write_text('{"records":[]}', encoding="utf-8")
    assert _read_object(studio_path) == {"records": []}


@pytest.mark.parametrize(
    ("reader", "filename"),
    [
        (lambda path: explain_exception_file(path, "EXC-1"), "ai.json"),
        (_load_json, "management_pack.json"),
        (_read_records, "enterprise.json"),
        (read_period_comparison, "period.json"),
        (read_rule_results, "rules.json"),
        (_read_object, "studio.json"),
    ],
)
def test_migrated_json_readers_reject_duplicate_keys_without_path_leak(
    tmp_path: Path,
    reader: JsonReader,
    filename: str,
) -> None:
    path = tmp_path / filename
    path.write_text('{"records":[],"records":[]}', encoding="utf-8")

    with pytest.raises(ValueError) as captured:
        reader(path)

    assert str(path) not in str(captured.value)


@pytest.mark.parametrize("reader", [_load_json, _read_records, read_period_comparison, read_rule_results])
def test_default_generated_json_readers_enforce_runtime_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reader: JsonReader,
) -> None:
    path = tmp_path / "artifact.json"
    path.write_text('{"records":[]}', encoding="utf-8")
    monkeypatch.setattr(
        generated_module,
        "GENERATED_ARTIFACT_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=4),
    )

    with pytest.raises(ValueError):
        reader(path)


def test_exception_explanation_reader_enforces_named_runtime_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "exceptions.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        summaries_module,
        "EXCEPTION_EXPLANATION_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=1),
    )

    with pytest.raises(ValueError, match="failed safety validation"):
        explain_exception_file(path, "EXC-1")


def test_studio_demo_reader_enforces_named_runtime_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "studio.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        demo_bridge_module,
        "STUDIO_DEMO_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=1),
    )

    with pytest.raises(ValueError, match="exceeds"):
        _read_object(path)


def test_exception_explanation_cli_uses_path_free_safe_error(tmp_path: Path) -> None:
    path = tmp_path / "sensitive-name.json"
    path.write_text('{"records":[],"records":[]}', encoding="utf-8")

    result = runner.invoke(
        app,
        ["explain", "exception", "--input", str(path), "--exception-id", "EXC-1"],
    )

    assert result.exit_code == 1
    assert "Exception JSON failed safety validation." in result.output
    assert str(path) not in result.output


def test_migrated_filesystem_entrypoints_have_no_direct_json_or_text_reader() -> None:
    root = Path(__file__).resolve().parents[1]
    targets = {
        "reconforge/ai/summaries.py": {"explain_exception_file"},
        "reconforge/dashboard/app.py": {"_load_json"},
        "reconforge/enterprise_demo.py": {"_read_records"},
        "reconforge/periods.py": {"read_period_comparison"},
        "reconforge/rules/engine.py": {"read_rule_results"},
        "reconforge/studio/demo_bridge.py": {"_read_object"},
    }
    forbidden: list[str] = []
    for relative, names in targets.items():
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for function in (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ):
            for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
                name = ast.unparse(call.func)
                if name in {"json.load", "json.loads"} or name.endswith(".read_text"):
                    forbidden.append(f"{relative}:{function.name}:{name}")
    assert forbidden == []
