from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from reconforge.engines.duckdb_engine import DuckDBEngine
from reconforge.io.ingress import (
    CURRENT_TABULAR_INGRESS_POLICY,
    FileIngressError,
    TabularIngressPolicy,
    validate_tabular_input,
)
from reconforge.io.readers import read_table
from reconforge.mappings.inspector import scan_input_headers
from reconforge.plugins.generic_csv import GenericCSVConnector
from reconforge.schemas import DatasetName


def _assert_code(exc: pytest.ExceptionInfo[FileIngressError], code: str) -> None:
    assert exc.value.code == code
    assert str(exc.value) == f"Input file rejected ({code})."


def _write_workbook(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()


def _write_minimal_xlsx(path: Path, members: dict[str, bytes]) -> None:
    defaults = {
        "[Content_Types].xml": b"<Types/>",
        "xl/workbook.xml": b"<workbook/>",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in {**defaults, **members}.items():
            archive.writestr(name, payload)


def test_valid_csv_and_static_xlsx_are_bounded_before_parsing(tmp_path: Path) -> None:
    csv_path = tmp_path / "records.csv"
    csv_path.write_text("id,amount\nA,10.25\nB,20.50\n", encoding="utf-8")
    csv_inspection = validate_tabular_input(csv_path)

    assert csv_inspection.policy_id == CURRENT_TABULAR_INGRESS_POLICY
    assert (csv_inspection.rows, csv_inspection.columns, csv_inspection.cells) == (2, 2, 6)
    assert read_table(csv_path).to_dict(orient="records") == [
        {"id": "A", "amount": "10.25"},
        {"id": "B", "amount": "20.50"},
    ]

    workbook_path = tmp_path / "records.xlsx"
    _write_workbook(workbook_path, [["id", "amount"], ["A", "10.25"]])
    xlsx_inspection = validate_tabular_input(workbook_path)

    assert xlsx_inspection.rows == 1
    assert xlsx_inspection.columns == 2
    assert xlsx_inspection.cells == 4
    assert xlsx_inspection.archive_members > 0
    assert read_table(workbook_path, nrows=1).iloc[0].to_dict() == {
        "id": "A",
        "amount": "10.25",
    }


def test_rejection_message_has_stable_code_without_path_or_source_value(tmp_path: Path) -> None:
    path = tmp_path / "client-secret-ledger.csv"
    path.write_text("key\nvery-sensitive-token\n", encoding="utf-8")

    with pytest.raises(FileIngressError) as exc:
        validate_tabular_input(path, policy=TabularIngressPolicy(max_file_bytes=8))

    _assert_code(exc, "file_size_limit")
    assert path.name not in str(exc.value)
    assert "very-sensitive-token" not in str(exc.value)


def test_non_regular_and_unsupported_files_fail_before_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "table.csv"
    directory.mkdir()
    with pytest.raises(FileIngressError) as directory_exc:
        validate_tabular_input(directory)
    _assert_code(directory_exc, "file_not_regular")

    unsupported = tmp_path / "table.json"
    unsupported.write_text("{}", encoding="utf-8")
    with pytest.raises(FileIngressError) as unsupported_exc:
        validate_tabular_input(unsupported)
    _assert_code(unsupported_exc, "file_type_unsupported")

    regular = tmp_path / "linked.csv"
    regular.write_text("id\n1\n", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda candidate: candidate == regular or original(candidate))
    with pytest.raises(FileIngressError) as symlink_exc:
        validate_tabular_input(regular)
    _assert_code(symlink_exc, "file_not_regular")


@pytest.mark.parametrize(
    ("contents", "policy", "code"),
    [
        ("a,b,c\n1,2,3\n", TabularIngressPolicy(max_columns=2), "table_column_limit"),
        ("a,b\n1,2\n3,4\n", TabularIngressPolicy(max_rows=1), "table_row_limit"),
        ("a,b\n1,2\n", TabularIngressPolicy(max_cells=3), "table_cell_limit"),
        ("a,b\n1\n", TabularIngressPolicy(), "csv_shape_invalid"),
    ],
)
def test_csv_shape_and_resource_budgets_fail_closed(
    tmp_path: Path,
    contents: str,
    policy: TabularIngressPolicy,
    code: str,
) -> None:
    path = tmp_path / "bounded.csv"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(FileIngressError) as exc:
        validate_tabular_input(path, policy=policy)

    _assert_code(exc, code)


@pytest.mark.parametrize(
    ("suffix", "payload"),
    [
        (".csv", b"PK\x03\x04not-a-csv"),
        (".xlsx", b"not-a-zip"),
        (".xls", b"not-an-ole-file"),
    ],
)
def test_extension_and_content_mismatch_is_rejected(
    tmp_path: Path,
    suffix: str,
    payload: bytes,
) -> None:
    path = tmp_path / f"mismatch{suffix}"
    path.write_bytes(payload)

    with pytest.raises(FileIngressError) as exc:
        validate_tabular_input(path)

    _assert_code(exc, "file_content_type_mismatch")


def test_xlsx_archive_rejects_traversal_duplicates_and_active_content(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.xlsx"
    _write_minimal_xlsx(traversal, {"../escape.xml": b"<x/>"})
    with pytest.raises(FileIngressError) as traversal_exc:
        validate_tabular_input(traversal)
    _assert_code(traversal_exc, "archive_member_path_unsafe")

    duplicate = tmp_path / "duplicate.xlsx"
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("xl/workbook.xml", b"<workbook/>")
        archive.writestr("XL/WORKBOOK.XML", b"<workbook/>")
    with pytest.raises(FileIngressError) as duplicate_exc:
        validate_tabular_input(duplicate)
    _assert_code(duplicate_exc, "archive_member_duplicate")

    active = tmp_path / "active.xlsx"
    _write_minimal_xlsx(active, {"xl/vbaProject.bin": b"active-content"})
    with pytest.raises(FileIngressError) as active_exc:
        validate_tabular_input(active)
    _assert_code(active_exc, "xlsx_active_content_forbidden")


def test_xlsx_archive_resource_budgets_are_checked_before_xml_parser(tmp_path: Path) -> None:
    path = tmp_path / "compressed.xlsx"
    _write_minimal_xlsx(path, {"xl/worksheets/sheet1.xml": b"A" * 20_000})

    with pytest.raises(FileIngressError) as ratio_exc:
        validate_tabular_input(
            path,
            policy=TabularIngressPolicy(max_archive_compression_ratio=2),
        )
    _assert_code(ratio_exc, "archive_compression_ratio_limit")

    with pytest.raises(FileIngressError) as total_exc:
        validate_tabular_input(
            path,
            policy=TabularIngressPolicy(
                max_archive_uncompressed_bytes=1_000,
                max_archive_compression_ratio=1_000_000,
            ),
        )
    _assert_code(total_exc, "archive_uncompressed_limit")


def test_xlsx_xml_entities_external_links_and_formulas_are_rejected(tmp_path: Path) -> None:
    entity = tmp_path / "entity.xlsx"
    _write_minimal_xlsx(
        entity,
        {"xl/worksheets/sheet1.xml": b"<!DOCTYPE x [<!ENTITY e 'boom'>]><worksheet/>"},
    )
    with pytest.raises(FileIngressError) as entity_exc:
        validate_tabular_input(entity)
    _assert_code(entity_exc, "xlsx_xml_declaration_forbidden")

    external = tmp_path / "external.xlsx"
    _write_minimal_xlsx(
        external,
        {
            "_rels/.rels": (
                b'<Relationships><Relationship TargetMode="External" '
                b'Target="https://invalid.example/resource"/></Relationships>'
            ),
        },
    )
    with pytest.raises(FileIngressError) as external_exc:
        validate_tabular_input(external)
    _assert_code(external_exc, "xlsx_external_reference_forbidden")

    formula = tmp_path / "formula.xlsx"
    _write_workbook(formula, [["id", "value"], ["A", '=HYPERLINK("https://invalid.example","x")']])
    with pytest.raises(FileIngressError) as formula_exc:
        validate_tabular_input(formula)
    _assert_code(formula_exc, "xlsx_formula_forbidden")


def test_xlsx_row_and_cell_budgets_are_checked_from_sheet_xml(tmp_path: Path) -> None:
    path = tmp_path / "bounded.xlsx"
    _write_workbook(path, [["a", "b"], [1, 2], [3, 4]])

    with pytest.raises(FileIngressError) as row_exc:
        validate_tabular_input(path, policy=TabularIngressPolicy(max_rows=1))
    _assert_code(row_exc, "table_row_limit")

    with pytest.raises(FileIngressError) as cell_exc:
        validate_tabular_input(path, policy=TabularIngressPolicy(max_cells=5))
    _assert_code(cell_exc, "table_cell_limit")

    with pytest.raises(FileIngressError) as column_exc:
        validate_tabular_input(path, policy=TabularIngressPolicy(max_columns=1))
    _assert_code(column_exc, "table_column_limit")


def test_xlsx_sparse_column_reference_and_aggregate_sheet_rows_are_bounded(tmp_path: Path) -> None:
    sparse = tmp_path / "sparse.xlsx"
    _write_minimal_xlsx(
        sparse,
        {"xl/worksheets/sheet1.xml": b'<worksheet><sheetData><row r="1"><c r="ZZ1"/></row></sheetData></worksheet>'},
    )
    with pytest.raises(FileIngressError) as sparse_exc:
        validate_tabular_input(sparse, policy=TabularIngressPolicy(max_columns=25))
    _assert_code(sparse_exc, "table_column_limit")

    multiple = tmp_path / "multiple.xlsx"
    sheet = b'<worksheet><sheetData><row r="1"><c r="A1"/></row><row r="2"><c r="A2"/></row></sheetData></worksheet>'
    _write_minimal_xlsx(
        multiple,
        {
            "xl/worksheets/sheet1.xml": sheet,
            "xl/worksheets/sheet2.xml": sheet,
        },
    )
    with pytest.raises(FileIngressError) as aggregate_exc:
        validate_tabular_input(multiple, policy=TabularIngressPolicy(max_rows=1))
    _assert_code(aggregate_exc, "table_row_limit")


def test_mapping_plugin_and_duckdb_direct_csv_paths_share_the_preflight(tmp_path: Path) -> None:
    path = tmp_path / "stock_moves.csv"
    path.write_bytes(b"PK\x03\x04not-a-csv")

    scans = scan_input_headers(tmp_path)
    assert len(scans) == 1
    assert scans[0].status == "error"
    assert scans[0].error == "Input file rejected (file_content_type_mismatch)."

    with pytest.raises(FileIngressError) as plugin_exc:
        GenericCSVConnector().load_data(tmp_path)
    _assert_code(plugin_exc, "file_content_type_mismatch")

    with pytest.raises(FileIngressError) as duckdb_exc:
        DuckDBEngine._register_dataset(
            object(),
            tmp_path,
            DatasetName.STOCK_MOVES,
            relation_name="stock_input",
        )
    _assert_code(duckdb_exc, "file_content_type_mismatch")
