"""Bounded exact-text readers for untrusted local business-record files."""

from __future__ import annotations

import csv
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, NoReturn

from reconforge.io.ingress import (
    FileIngressError,
    TabularIngressPolicy,
    validate_tabular_input,
)
from reconforge.io.structured import (
    StructuredDocumentError,
    StructuredDocumentPolicy,
    read_json_document,
)

BUSINESS_RECORD_INGRESS_PROFILE = "business-record-ingress-v1"
BUSINESS_RECORD_MAX_FILE_BYTES = 64 * 1024 * 1024
BUSINESS_RECORD_MAX_RECORDS = 250_000
BUSINESS_RECORD_MAX_FIELDS = 512
BUSINESS_RECORD_MAX_CELLS = 10_000_000
BUSINESS_RECORD_MAX_FIELD_CHARACTERS = 128_000
BUSINESS_RECORD_JSON_MAX_NODES = 2_000_000
BUSINESS_RECORD_JSON_MAX_DEPTH = 32
BUSINESS_RECORD_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=BUSINESS_RECORD_MAX_FILE_BYTES,
    max_nodes=BUSINESS_RECORD_JSON_MAX_NODES,
    max_depth=BUSINESS_RECORD_JSON_MAX_DEPTH,
    max_collection_items=BUSINESS_RECORD_MAX_RECORDS,
    max_scalar_characters=BUSINESS_RECORD_MAX_FIELD_CHARACTERS,
    max_yaml_aliases=1,
)
BUSINESS_RECORD_CSV_POLICY = TabularIngressPolicy(
    max_file_bytes=BUSINESS_RECORD_MAX_FILE_BYTES,
    max_rows=BUSINESS_RECORD_MAX_RECORDS,
    max_columns=BUSINESS_RECORD_MAX_FIELDS,
    max_cells=BUSINESS_RECORD_MAX_CELLS,
    max_csv_field_characters=BUSINESS_RECORD_MAX_FIELD_CHARACTERS,
)
_READ_CHUNK_BYTES = 1024 * 1024
_GENERIC_ENVELOPE_KEYS = ("records", "rows", "items", "data")


class RecordIngressError(ValueError):
    """Safe record-ingress rejection containing no source path or value."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Business record input rejected ({code}).")


@dataclass(frozen=True)
class BusinessRecordDocument:
    """Parsed records bound to the exact local bytes that produced them."""

    source_path: Path
    records: list[dict[str, Any]]
    checksum_sha256: str
    size_bytes: int
    profile_id: str
    format: str


def _reject(code: str) -> NoReturn:
    raise RecordIngressError(code)


def _path_is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RecordIngressError("record_file_unreadable") from exc
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(file_attributes & reparse_attribute)


def _bounded_fingerprint(path: Path, *, max_file_bytes: int) -> tuple[str, int]:
    if _path_is_reparse(path):
        _reject("record_file_not_regular")
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            _reject("record_file_not_regular")
        if metadata.st_size <= 0:
            _reject("record_file_empty")
        if metadata.st_size > max_file_bytes:
            _reject("record_file_size_limit")
        digest = sha256()
        total = 0
        with path.open("rb") as handle:
            if os.fstat(handle.fileno()).st_size != metadata.st_size:
                _reject("record_file_changed")
            for chunk in iter(lambda: handle.read(_READ_CHUNK_BYTES), b""):
                total += len(chunk)
                if total > max_file_bytes:
                    _reject("record_file_size_limit")
                digest.update(chunk)
            if total != metadata.st_size or os.fstat(handle.fileno()).st_size != metadata.st_size:
                _reject("record_file_changed")
    except RecordIngressError:
        raise
    except OSError as exc:
        raise RecordIngressError("record_file_unreadable") from exc
    return digest.hexdigest(), total


def _stable_result(
    path: Path,
    *,
    before_checksum: str,
    before_size: int,
    max_file_bytes: int,
) -> tuple[str, int]:
    after_checksum, after_size = _bounded_fingerprint(
        path,
        max_file_bytes=max_file_bytes,
    )
    if before_checksum != after_checksum or before_size != after_size:
        _reject("record_file_changed")
    return after_checksum, after_size


def _validate_records(records: object) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        _reject("json_record_collection_required")
    if len(records) > BUSINESS_RECORD_MAX_RECORDS:
        _reject("record_count_limit")
    result: list[dict[str, Any]] = []
    cells = 0
    for record in records:
        if not isinstance(record, dict):
            _reject("json_record_not_object")
        if len(record) > BUSINESS_RECORD_MAX_FIELDS:
            _reject("record_field_limit")
        cells += len(record)
        if cells > BUSINESS_RECORD_MAX_CELLS:
            _reject("record_cell_limit")
        result.append(dict(record))
    return result


def _json_records(
    payload: object,
    *,
    envelope_keys: tuple[str, ...],
    allow_single_object: bool,
) -> list[dict[str, Any]]:
    raw_records: object
    if isinstance(payload, list):
        raw_records = payload
    elif isinstance(payload, dict):
        present = [key for key in envelope_keys if key in payload]
        if len(present) > 1:
            _reject("json_record_envelope_ambiguous")
        if present:
            raw_records = payload[present[0]]
        elif allow_single_object:
            raw_records = [payload]
        else:
            _reject("json_record_collection_required")
    else:
        _reject("json_record_collection_required")
    return _validate_records(raw_records)


def read_json_record_document(
    path: Path,
    *,
    envelope_keys: tuple[str, ...],
    allow_single_object: bool = False,
) -> BusinessRecordDocument:
    """Read one bounded JSON record list while preserving fractional lexemes."""

    if not envelope_keys or len(set(envelope_keys)) != len(envelope_keys):
        raise ValueError("envelope_keys must be a non-empty unique tuple")
    if path.suffix.lower() != ".json":
        _reject("record_file_type_unsupported")
    before_checksum, before_size = _bounded_fingerprint(
        path,
        max_file_bytes=BUSINESS_RECORD_JSON_POLICY.max_file_bytes,
    )
    try:
        payload = read_json_document(
            path,
            preserve_float_lexemes=True,
            policy=BUSINESS_RECORD_JSON_POLICY,
        )
    except StructuredDocumentError as exc:
        raise RecordIngressError(exc.code) from exc
    records = _json_records(
        payload,
        envelope_keys=envelope_keys,
        allow_single_object=allow_single_object,
    )
    checksum, size = _stable_result(
        path,
        before_checksum=before_checksum,
        before_size=before_size,
        max_file_bytes=BUSINESS_RECORD_JSON_POLICY.max_file_bytes,
    )
    return BusinessRecordDocument(
        source_path=path,
        records=records,
        checksum_sha256=checksum,
        size_bytes=size,
        profile_id=BUSINESS_RECORD_INGRESS_PROFILE,
        format="json",
    )


def _read_csv_record_document(path: Path) -> BusinessRecordDocument:
    before_checksum, before_size = _bounded_fingerprint(
        path,
        max_file_bytes=BUSINESS_RECORD_CSV_POLICY.max_file_bytes,
    )
    try:
        inspection = validate_tabular_input(path, policy=BUSINESS_RECORD_CSV_POLICY)
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            fieldnames = reader.fieldnames
            if (
                fieldnames is None
                or any(not field.strip() for field in fieldnames)
                or len(fieldnames) != len(set(fieldnames))
            ):
                _reject("csv_header_ambiguous")
            records = [dict(row) for row in reader]
    except RecordIngressError:
        raise
    except FileIngressError as exc:
        raise RecordIngressError(exc.code) from exc
    except (OSError, UnicodeError, csv.Error) as exc:
        raise RecordIngressError("csv_structure_invalid") from exc
    if len(records) != inspection.rows:
        _reject("record_file_changed")
    checksum, size = _stable_result(
        path,
        before_checksum=before_checksum,
        before_size=before_size,
        max_file_bytes=BUSINESS_RECORD_CSV_POLICY.max_file_bytes,
    )
    return BusinessRecordDocument(
        source_path=path,
        records=records,
        checksum_sha256=checksum,
        size_bytes=size,
        profile_id=BUSINESS_RECORD_INGRESS_PROFILE,
        format="csv",
    )


def read_business_record_document(path: Path) -> BusinessRecordDocument:
    """Read bounded CSV or generic JSON records from an already resolved path."""

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv_record_document(path)
    if suffix == ".json":
        return read_json_record_document(
            path,
            envelope_keys=_GENERIC_ENVELOPE_KEYS,
            allow_single_object=True,
        )
    _reject("record_file_type_unsupported")


__all__ = [
    "BUSINESS_RECORD_CSV_POLICY",
    "BUSINESS_RECORD_INGRESS_PROFILE",
    "BUSINESS_RECORD_JSON_POLICY",
    "BusinessRecordDocument",
    "RecordIngressError",
    "read_business_record_document",
    "read_json_record_document",
]
