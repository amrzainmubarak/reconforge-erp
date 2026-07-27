from __future__ import annotations

import ast
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.evidence import binder as binder_module
from reconforge.evidence.binder import collect_evidence_cases, generate_evidence_binder
from reconforge.io import generated as generated_module
from reconforge.io.generated import GeneratedArtifactError
from reconforge.io.ingress import TabularIngressPolicy
from reconforge.review import state as review_module
from reconforge.review.state import collect_exception_frame
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
)

runner = CliRunner()


def _write_exceptions(path: Path, *, rows: int = 1) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    source = path / "stock_gl_all_exceptions.csv"
    source.write_text(
        "exception_type,risk_score,source_document,total_cost\n"
        + "".join(f"stock_without_gl,61,DOC-{index},{index}.001\n" for index in range(1, rows + 1)),
        encoding="utf-8",
    )
    return source


def test_fi005_consumers_select_explicit_financial_representation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.joinpath("stock_gl_all_exceptions.csv").write_text(
        "exception_type,risk_score\nx,61\n",
        encoding="utf-8",
    )
    binder_modes: list[str] = []
    review_modes: list[str] = []
    binder_reader = binder_module.read_generated_csv_document
    review_reader = review_module.read_generated_csv_document

    def read_binder(path: Path, *, mode: str = "display"):  # type: ignore[no-untyped-def]
        binder_modes.append(mode)
        return binder_reader(path, mode=mode)  # type: ignore[arg-type]

    def read_review(path: Path, *, mode: str = "display"):  # type: ignore[no-untyped-def]
        review_modes.append(mode)
        return review_reader(path, mode=mode)  # type: ignore[arg-type]

    monkeypatch.setattr(binder_module, "read_generated_csv_document", read_binder)
    monkeypatch.setattr(review_module, "read_generated_csv_document", read_review)

    collect_evidence_cases(tmp_path, financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY)
    collect_evidence_cases(tmp_path, financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY)
    collect_exception_frame(tmp_path, financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY)
    collect_exception_frame(tmp_path, financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY)

    assert binder_modes == ["display", "exact-text"]
    assert review_modes == ["display", "exact-text"]


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"exception_type,risk_score,risk_score\nx,61,62\n", "generated_csv_header_ambiguous"),
        (b"exception_type,risk_score\nx\n", "csv_shape_invalid"),
        (b"exception_type,risk_score\nx,\xff\n", "csv_structure_invalid"),
    ],
)
@pytest.mark.parametrize("consumer", ["evidence", "review"])
def test_fi005_consumers_reject_hostile_csv(
    tmp_path: Path,
    raw: bytes,
    code: str,
    consumer: str,
) -> None:
    tmp_path.joinpath("stock_gl_all_exceptions.csv").write_bytes(raw)

    with pytest.raises(GeneratedArtifactError) as captured:
        if consumer == "evidence":
            collect_evidence_cases(tmp_path)
        else:
            collect_exception_frame(tmp_path)

    assert captured.value.code == code
    assert str(tmp_path) not in str(captured.value)


@pytest.mark.parametrize("consumer", ["evidence", "review"])
def test_fi005_consumers_enforce_row_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    consumer: str,
) -> None:
    _write_exceptions(tmp_path, rows=2)
    monkeypatch.setattr(
        generated_module,
        "GENERATED_ARTIFACT_CSV_POLICY",
        TabularIngressPolicy(max_rows=1),
    )

    with pytest.raises(GeneratedArtifactError) as captured:
        if consumer == "evidence":
            collect_evidence_cases(tmp_path)
        else:
            collect_exception_frame(tmp_path)

    assert captured.value.code == "table_row_limit"


def test_evidence_binder_parses_each_selected_csv_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _write_exceptions(source, rows=3)
    source.joinpath("stock_gl_matched_transactions.csv").write_text(
        "work_order,source_document,stock_amount\nWO-1,DOC-1,1.001\n",
        encoding="utf-8",
    )
    rules = source / "rules"
    rules.mkdir()
    rules.joinpath("rule_results.csv").write_text(
        "rule_name,evidence_fields\nR-1,DOC-1\n",
        encoding="utf-8",
    )
    calls: Counter[Path] = Counter()
    original = binder_module.read_generated_csv_document

    def counted(path: Path, *, mode: str = "display"):  # type: ignore[no-untyped-def]
        calls[path] += 1
        return original(path, mode=mode)  # type: ignore[arg-type]

    monkeypatch.setattr(binder_module, "read_generated_csv_document", counted)

    generate_evidence_binder(
        source,
        tmp_path / "evidence",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    assert calls == Counter(
        {
            source / "stock_gl_all_exceptions.csv": 1,
            source / "stock_gl_matched_transactions.csv": 1,
            rules / "rule_results.csv": 1,
        },
    )


def test_evidence_index_fingerprint_names_exact_parsed_csv_bytes(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source = _write_exceptions(source_dir)
    raw = source.read_bytes()
    output = tmp_path / "evidence"

    generate_evidence_binder(
        source_dir,
        output,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    payload = json.loads(output.joinpath("evidence_index.json").read_text(encoding="utf-8"))
    assert payload["input_files"] == [
        {
            "path": source.name,
            "size_bytes": len(raw),
            "sha256": sha256(raw).hexdigest(),
        },
    ]


def test_evidence_binder_rejects_csv_changed_after_cached_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "source"
    source = _write_exceptions(source_dir)
    original = binder_module.write_evidence_index_html

    def mutate_after_cases(*args, **kwargs):  # type: ignore[no-untyped-def]
        result = original(*args, **kwargs)
        source.write_text(
            "exception_type,risk_score,source_document,total_cost\nchanged,99,DOC-X,9\n",
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(binder_module, "write_evidence_index_html", mutate_after_cases)

    with pytest.raises(GeneratedArtifactError) as captured:
        generate_evidence_binder(
            source_dir,
            tmp_path / "evidence",
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    assert captured.value.code == "generated_file_changed"


@pytest.mark.parametrize(
    "command",
    [
        ["report", "evidence-binder", "--input", "{input}", "--output", "{output}"],
        ["review", "list", "--input", "{input}"],
        ["review", "export", "--input", "{input}", "--output", "{output}"],
    ],
)
def test_fi005_cli_surfaces_fail_safely_without_path_or_traceback(
    tmp_path: Path,
    command: list[str],
) -> None:
    source = tmp_path / "987654321.01"
    source.mkdir()
    source.joinpath("stock_gl_all_exceptions.csv").write_text(
        "exception_type,risk_score,risk_score\nx,61,62\n",
        encoding="utf-8",
    )
    output = tmp_path / "should-not-exist.xlsx"
    args = [part.format(input=source, output=output) for part in command]

    result = runner.invoke(app, args)

    assert result.exit_code == 1
    assert "Generated report input failed safety validation." in result.output
    assert str(source) not in result.output
    assert "Traceback" not in result.output
    assert not output.exists()


def test_fi005_missing_optional_csv_remains_empty(tmp_path: Path) -> None:
    assert collect_evidence_cases(tmp_path) == []
    assert collect_exception_frame(tmp_path).empty


def test_fi005_entrypoints_have_no_direct_dataframe_parser() -> None:
    root = Path(__file__).resolve().parents[1]
    targets = {
        "reconforge/evidence/binder.py": {"_read_csv_if_exists"},
        "reconforge/review/state.py": {"collect_exception_frame"},
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
                if name == "pd.read_csv":
                    forbidden.append(f"{relative}:{function.name}:{name}")
    assert forbidden == []
