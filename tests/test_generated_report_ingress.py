from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from reconforge.io import generated as generated_module
from reconforge.io.generated import (
    GeneratedArtifactError,
    read_generated_csv_document,
)
from reconforge.io.ingress import TabularIngressPolicy
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.reports.management_pack import (
    _evidence_coverage_pct,
    _json_payload,
    _recurring_exception_count,
)
from reconforge.variance import load_summary_metrics


def test_generated_csv_exact_text_mode_preserves_source_lexemes(tmp_path: Path) -> None:
    path = tmp_path / "report.csv"
    path.write_text("code,label,amount\n001,NA,2.500\n", encoding="utf-8")

    document = read_generated_csv_document(path, mode="exact-text")

    assert document.mode == "exact-text"
    assert document.frame.to_dict(orient="records") == [
        {"code": "001", "label": "NA", "amount": "2.500"},
    ]


def test_generated_csv_default_mode_remains_display_compatible(tmp_path: Path) -> None:
    path = tmp_path / "report.csv"
    path.write_text("code,label,amount\n001,NA,2.500\n", encoding="utf-8")

    document = read_generated_csv_document(path)

    assert document.mode == "display"
    assert document.frame.to_dict(orient="records") == [
        {"code": 1, "label": "NA", "amount": 2.5},
    ]


def test_generated_csv_rejects_unknown_mode_before_file_access(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"

    with pytest.raises(GeneratedArtifactError) as captured:
        read_generated_csv_document(missing, mode="binary")  # type: ignore[arg-type]

    assert captured.value.code == "generated_csv_mode_unsupported"


def test_variance_readers_preserve_exact_json_and_csv_numbers(tmp_path: Path) -> None:
    tmp_path.joinpath("management_pack.json").write_text(
        '{"executive_summary":[{"metric":"json_amount","value":2.500001}]}',
        encoding="utf-8",
    )
    tmp_path.joinpath("control_value_summary.csv").write_text(
        "metric,value\ncsv_amount,0002.500001\n",
        encoding="utf-8",
    )

    metrics = load_summary_metrics(tmp_path)

    assert metrics["executive_summary.json_amount"] == Decimal("2.500001")
    assert metrics["control_value_summary.csv_amount"] == Decimal("2.500001")


@pytest.mark.parametrize(
    "raw",
    [
        b'{"value":1,"value":2}',
        b'{"value":NaN}',
        b"\xff",
        b"[]",
    ],
)
def test_variance_json_reader_fails_closed_for_hostile_artifacts(
    tmp_path: Path,
    raw: bytes,
) -> None:
    tmp_path.joinpath("management_pack.json").write_bytes(raw)

    with pytest.raises(ValueError, match="No summary metrics found"):
        load_summary_metrics(tmp_path)


@pytest.mark.parametrize(
    "raw",
    [
        b"metric,metric\na,b\n",
        b"metric,value\na\n",
        b"metric,value\na,\xff\n",
    ],
)
def test_variance_csv_reader_fails_closed_for_hostile_artifacts(
    tmp_path: Path,
    raw: bytes,
) -> None:
    tmp_path.joinpath("control_value_summary.csv").write_bytes(raw)

    with pytest.raises(ValueError, match="No summary metrics found"):
        load_summary_metrics(tmp_path)


def test_variance_readers_enforce_runtime_resource_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.joinpath("management_pack.json").write_text('{"value":1}', encoding="utf-8")
    monkeypatch.setattr(
        generated_module,
        "GENERATED_ARTIFACT_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=4),
    )

    with pytest.raises(ValueError, match="No summary metrics found"):
        load_summary_metrics(tmp_path)

    tmp_path.joinpath("management_pack.json").unlink()
    tmp_path.joinpath("control_value_summary.csv").write_text(
        "metric,value\na,1\nb,2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        generated_module,
        "GENERATED_ARTIFACT_CSV_POLICY",
        TabularIngressPolicy(max_rows=1),
    )

    with pytest.raises(ValueError, match="No summary metrics found"):
        load_summary_metrics(tmp_path)


def test_management_json_consumers_fail_closed_for_hostile_artifacts(tmp_path: Path) -> None:
    period = tmp_path / "period_comparison.json"
    period.write_text('{"recurring_exceptions":[],"recurring_exceptions":[{}]}', encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    evidence.joinpath("evidence_index.json").write_text('{"case_count":NaN}', encoding="utf-8")

    assert _json_payload(period) == {}
    assert _recurring_exception_count(tmp_path) == "not_available"
    assert _evidence_coverage_pct(1, tmp_path) == "not_available"


def test_fi006_entrypoints_have_no_direct_file_or_parser_calls() -> None:
    root = Path(__file__).resolve().parents[1]
    targets = {
        "reconforge/variance.py": {"_extract_csv_metrics", "_extract_json_metrics"},
        "reconforge/reports/management_pack.py": {"_json_payload"},
    }
    forbidden: list[str] = []
    for relative, function_names in targets.items():
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for function in (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in function_names
        ):
            for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
                name = ast.unparse(call.func)
                if name in {"pd.read_csv", "json.load", "json.loads"} or name.endswith(".read_text"):
                    forbidden.append(f"{relative}:{function.name}:{name}")
    assert forbidden == []
