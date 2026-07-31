"""Fail-closed inspection for untrusted local tabular inputs."""

from __future__ import annotations

import csv
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

CURRENT_TABULAR_INGRESS_POLICY = "tabular-file-ingress-v1"
_CSV_SUFFIX = ".csv"
_XLSX_SUFFIX = ".xlsx"
_XLS_SUFFIX = ".xls"
_SUPPORTED_SUFFIXES = frozenset({_CSV_SUFFIX, _XLSX_SUFFIX, _XLS_SUFFIX})
_ZIP_LOCAL_FILE_MAGIC = b"PK\x03\x04"
_OLE_COMPOUND_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_XLSX_CELL_REFERENCE = re.compile(r"^([A-Za-z]+)[1-9][0-9]*$")
_EXTERNAL_RELATIONSHIP = re.compile(rb"targetmode\s*=\s*['\"]external['\"]", re.IGNORECASE)
_FORBIDDEN_XML_DECLARATIONS = (b"<!DOCTYPE", b"<!ENTITY")
_ALLOWED_ZIP_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_REQUIRED_XLSX_MEMBERS = frozenset({"[Content_Types].xml", "xl/workbook.xml"})
_FORBIDDEN_XLSX_PREFIXES = (
    "xl/activex/",
    "xl/embeddings/",
    "xl/externallinks/",
)


class FileIngressError(ValueError):
    """Safe tabular-ingress rejection with a stable non-sensitive code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Input file rejected ({code}).")


@dataclass(frozen=True)
class TabularIngressPolicy:
    """Resource and active-content ceilings for one local tabular input."""

    policy_id: str = CURRENT_TABULAR_INGRESS_POLICY
    max_file_bytes: int = 64 * 1024 * 1024
    max_rows: int = 1_000_000
    max_columns: int = 2_048
    max_cells: int = 20_000_000
    max_csv_field_characters: int = 128_000
    max_archive_members: int = 4_096
    max_archive_member_bytes: int = 128 * 1024 * 1024
    max_archive_uncompressed_bytes: int = 256 * 1024 * 1024
    max_archive_compression_ratio: int = 1_000

    def __post_init__(self) -> None:
        values = (
            self.max_file_bytes,
            self.max_rows,
            self.max_columns,
            self.max_cells,
            self.max_csv_field_characters,
            self.max_archive_members,
            self.max_archive_member_bytes,
            self.max_archive_uncompressed_bytes,
            self.max_archive_compression_ratio,
        )
        if self.policy_id != CURRENT_TABULAR_INGRESS_POLICY or any(
            isinstance(value, bool) or value <= 0 for value in values
        ):
            raise ValueError("Invalid tabular ingress policy")


DEFAULT_TABULAR_INGRESS_POLICY = TabularIngressPolicy()


@dataclass(frozen=True)
class TabularInputInspection:
    """Bounded pre-parser facts without source values or local path disclosure."""

    policy_id: str
    suffix: str
    size_bytes: int
    rows: int
    columns: int
    cells: int
    archive_members: int = 0
    archive_uncompressed_bytes: int = 0


def _reject(code: str) -> NoReturn:
    raise FileIngressError(code)


def _regular_file(path: Path, policy: TabularIngressPolicy) -> tuple[str, int, bytes]:
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        _reject("file_type_unsupported")
    try:
        if path.is_symlink() or not path.exists() or not path.is_file():
            _reject("file_not_regular")
        size = path.stat().st_size
        with path.open("rb") as handle:
            magic = handle.read(8)
    except FileIngressError:
        raise
    except OSError as exc:
        raise FileIngressError("file_unreadable") from exc
    if size <= 0:
        _reject("file_empty")
    if size > policy.max_file_bytes:
        _reject("file_size_limit")
    return suffix, size, magic


def _inspect_csv(path: Path, policy: TabularIngressPolicy) -> tuple[int, int, int]:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(4)
        if prefix.startswith(_ZIP_LOCAL_FILE_MAGIC) or prefix == _OLE_COMPOUND_MAGIC[:4]:
            _reject("file_content_type_mismatch")
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            try:
                header = next(reader)
            except StopIteration:
                _reject("csv_header_missing")
            columns = len(header)
            if columns <= 0:
                _reject("csv_header_missing")
            if columns > policy.max_columns:
                _reject("table_column_limit")
            if any(len(field) > policy.max_csv_field_characters for field in header):
                _reject("csv_field_limit")

            rows = 0
            cells = columns
            for row in reader:
                rows += 1
                if rows > policy.max_rows:
                    _reject("table_row_limit")
                if len(row) != columns:
                    _reject("csv_shape_invalid")
                if any(len(field) > policy.max_csv_field_characters for field in row):
                    _reject("csv_field_limit")
                cells += len(row)
                if cells > policy.max_cells:
                    _reject("table_cell_limit")
    except FileIngressError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FileIngressError("csv_structure_invalid") from exc
    return rows, columns, cells


def _safe_archive_name(name: str) -> bool:
    if not name or "\\" in name or any(ord(character) < 32 or ord(character) == 127 for character in name):
        return False
    if name.startswith("/") or _WINDOWS_DRIVE_PREFIX.match(name):
        return False
    parts = PurePosixPath(name).parts
    return bool(parts) and all(part not in {"", ".", ".."} for part in parts)


def _zip_member_is_symlink(member: zipfile.ZipInfo) -> bool:
    mode = (member.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def _member_has_forbidden_xml(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
) -> bool:
    overlap = max(len(pattern) for pattern in _FORBIDDEN_XML_DECLARATIONS) - 1
    carry = b""
    with archive.open(member, "r") as handle:
        while True:
            chunk = handle.read(64 * 1024)
            if not chunk:
                return False
            window = (carry + chunk).upper()
            if any(pattern in window for pattern in _FORBIDDEN_XML_DECLARATIONS):
                return True
            carry = window[-overlap:]


def _member_has_external_relationship(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
) -> bool:
    carry = b""
    with archive.open(member, "r") as handle:
        while True:
            chunk = handle.read(64 * 1024)
            if not chunk:
                return False
            window = carry + chunk
            if _EXTERNAL_RELATIONSHIP.search(window):
                return True
            carry = window[-128:]


def _xlsx_sheet_counts(
    archive: zipfile.ZipFile,
    worksheets: list[zipfile.ZipInfo],
    policy: TabularIngressPolicy,
) -> tuple[int, int, int]:
    total_rows = 0
    total_cells = 0
    maximum_columns = 0
    for worksheet in worksheets:
        sheet_rows = 0
        row_cells = 0
        try:
            with archive.open(worksheet, "r") as handle:
                for event, element in ElementTree.iterparse(
                    handle,
                    events=("start", "end"),
                    forbid_dtd=True,
                    forbid_entities=True,
                    forbid_external=True,
                ):
                    if event == "start" and isinstance(element.tag, str):
                        name = element.tag.rsplit("}", 1)[-1]
                        if name == "f":
                            _reject("xlsx_formula_forbidden")
                        if name == "row":
                            sheet_rows += 1
                            row_cells = 0
                            if total_rows + sheet_rows > policy.max_rows + 1:
                                _reject("table_row_limit")
                        elif name == "c":
                            row_cells += 1
                            maximum_columns = max(maximum_columns, row_cells)
                            if row_cells > policy.max_columns:
                                _reject("table_column_limit")
                            reference = element.attrib.get("r")
                            if reference:
                                match = _XLSX_CELL_REFERENCE.fullmatch(reference)
                                if match is None:
                                    _reject("xlsx_structure_invalid")
                                column_index = 0
                                for character in match.group(1).upper():
                                    column_index = column_index * 26 + ord(character) - ord("A") + 1
                                    if column_index > policy.max_columns:
                                        _reject("table_column_limit")
                                maximum_columns = max(maximum_columns, column_index)
                            total_cells += 1
                            if total_cells > policy.max_cells:
                                _reject("table_cell_limit")
                    if event == "end":
                        element.clear()
        except FileIngressError:
            raise
        except (
            DefusedXmlException,
            ElementTree.ParseError,
            OSError,
            RuntimeError,
            zipfile.BadZipFile,
        ) as exc:
            raise FileIngressError("xlsx_xml_invalid") from exc
        total_rows += max(0, sheet_rows - 1)
    return total_rows, maximum_columns, total_cells


def _inspect_xlsx(path: Path, policy: TabularIngressPolicy) -> tuple[int, int, int, int, int]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            if not members or len(members) > policy.max_archive_members:
                _reject("archive_member_limit")
            names: set[str] = set()
            casefolded_names: set[str] = set()
            total_uncompressed = 0
            worksheets: list[zipfile.ZipInfo] = []
            xml_members: list[zipfile.ZipInfo] = []
            relationship_members: list[zipfile.ZipInfo] = []

            for member in members:
                name = member.filename
                folded = name.casefold()
                if not _safe_archive_name(name) or _zip_member_is_symlink(member):
                    _reject("archive_member_path_unsafe")
                if name in names or folded in casefolded_names:
                    _reject("archive_member_duplicate")
                names.add(name)
                casefolded_names.add(folded)
                if member.flag_bits & 0x1:
                    _reject("archive_member_encrypted")
                if member.compress_type not in _ALLOWED_ZIP_COMPRESSION:
                    _reject("archive_compression_unsupported")
                if member.file_size > policy.max_archive_member_bytes:
                    _reject("archive_member_size_limit")
                total_uncompressed += member.file_size
                if total_uncompressed > policy.max_archive_uncompressed_bytes:
                    _reject("archive_uncompressed_limit")
                if member.file_size > max(1, member.compress_size) * policy.max_archive_compression_ratio:
                    _reject("archive_compression_ratio_limit")
                if folded.endswith("/vbaproject.bin") or folded.startswith(_FORBIDDEN_XLSX_PREFIXES):
                    _reject("xlsx_active_content_forbidden")
                if folded.endswith(".xml") or folded.endswith(".rels"):
                    xml_members.append(member)
                if folded.startswith("xl/worksheets/") and folded.endswith(".xml"):
                    worksheets.append(member)
                if folded.endswith(".rels"):
                    relationship_members.append(member)

            if not _REQUIRED_XLSX_MEMBERS.issubset(names):
                _reject("xlsx_structure_invalid")
            for member in xml_members:
                if _member_has_forbidden_xml(archive, member):
                    _reject("xlsx_xml_declaration_forbidden")
            for member in relationship_members:
                if _member_has_external_relationship(archive, member):
                    _reject("xlsx_external_reference_forbidden")
            rows, columns, cells = _xlsx_sheet_counts(archive, worksheets, policy)
            return rows, columns, cells, len(members), total_uncompressed
    except FileIngressError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise FileIngressError("xlsx_archive_invalid") from exc


def validate_tabular_input(
    path: Path | str,
    *,
    policy: TabularIngressPolicy = DEFAULT_TABULAR_INGRESS_POLICY,
) -> TabularInputInspection:
    """Inspect one CSV/XLSX/XLS file before a dataframe or SQL parser sees it."""

    source = Path(path)
    suffix, size, magic = _regular_file(source, policy)
    if suffix == _CSV_SUFFIX:
        rows, columns, cells = _inspect_csv(source, policy)
        return TabularInputInspection(policy.policy_id, suffix, size, rows, columns, cells)
    if suffix == _XLSX_SUFFIX:
        if not magic.startswith(_ZIP_LOCAL_FILE_MAGIC):
            _reject("file_content_type_mismatch")
        rows, columns, cells, members, uncompressed = _inspect_xlsx(source, policy)
        return TabularInputInspection(
            policy.policy_id,
            suffix,
            size,
            rows,
            columns,
            cells,
            members,
            uncompressed,
        )
    if magic != _OLE_COMPOUND_MAGIC:
        _reject("file_content_type_mismatch")
    return TabularInputInspection(policy.policy_id, suffix, size, 0, 0, 0)


__all__ = [
    "CURRENT_TABULAR_INGRESS_POLICY",
    "DEFAULT_TABULAR_INGRESS_POLICY",
    "FileIngressError",
    "TabularIngressPolicy",
    "TabularInputInspection",
    "validate_tabular_input",
]
