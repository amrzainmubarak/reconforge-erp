"""Client handoff pack generation."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from shutil import rmtree
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Any, Literal

from reconforge import __version__
from reconforge.io.ingress import FileIngressError, validate_tabular_input
from reconforge.io.structured import StructuredDocumentError, read_json_document
from reconforge.io.writers import json_default
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
    validate_financial_input_policy,
)
from reconforge.utils.time import utc_now_text

CLIENT_PACK_MANIFEST_SCHEMA_VERSION = 2
CLIENT_PACK_REDACTION_ALGORITHM_VERSION = "client-pack-redaction-v2"
_CLIENT_PACK_ARTIFACT_TYPE = "reconforge-client-pack-manifest"
_PUBLICATION_MARKER_ARTIFACT_TYPE = "reconforge-client-pack-publication-transaction"
_PUBLICATION_MARKER_SCHEMA_VERSION = 1
_PUBLICATION_MARKER_PHASES = frozenset({"prepared", "previous-moved", "published"})
_PUBLICATION_MARKER_INTEGRITY_BOUNDARY = (
    "Local bounded tree and marker SHA-256 digests provide integrity/self-consistency only. "
    "They are not authentication, a digital signature, source provenance, or protection "
    "against an attacker who can rewrite the marker and publication directories."
)
_CLIENT_PACK_INTEGRITY_BOUNDARY = (
    "Local source/output content digests only; redaction remains best-effort "
    "and this artifact is not a signature, disclosure approval, audit opinion, "
    "compliance certification, or proof of source-system authenticity."
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CLIENT_PACK_MAX_SOURCE_FILES = 10_000
CLIENT_PACK_MAX_DIRECTORY_ENTRIES = 20_000
CLIENT_PACK_MAX_FILE_BYTES = 64 * 1024 * 1024
CLIENT_PACK_MAX_TOTAL_SOURCE_BYTES = 512 * 1024 * 1024
CLIENT_PACK_MAX_TEXT_LINE_CHARACTERS = 1024 * 1024
_CLIENT_PACK_GENERATED_FILE_ALLOWANCE = 4
_CLIENT_PACK_GENERATED_BYTE_ALLOWANCE = 16 * 1024 * 1024
_CLIENT_PACK_IO_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ClientPackOptions:
    """Sharing controls for generated client handoff packs."""

    redact_names: bool = False
    redact_amounts: bool = False
    exclude_raw_records: bool = False
    summary_only: bool = False
    exclude_evidence: bool = False
    include_manifest_checksums: bool = False
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY

    def __post_init__(self) -> None:
        """Keep direct option construction on the supported policy boundary."""

        normalized = validate_financial_input_policy(self.financial_input_policy)
        object.__setattr__(self, "financial_input_policy", normalized)

    @property
    def redaction_requested(self) -> bool:
        return self.redact_names or self.redact_amounts


@dataclass(frozen=True)
class ClientPackArtifacts:
    """Generated client handoff pack paths."""

    output_dir: Path
    included_files: list[Path]
    missing_optional_files: list[str]
    excluded_files: list[str]
    manifest_path: Path
    summary_path: Path
    next_steps_path: Path
    privacy_note_path: Path


@dataclass(frozen=True)
class ClientPackManifestDocument:
    """A historical v1 or verified current client-pack manifest."""

    schema_version: Literal[1, 2]
    verification_status: Literal["legacy-unverified", "verified"]
    payload: dict[str, Any]


@dataclass(frozen=True)
class ClientPackPublicationRecovery:
    """Result of one explicit, integrity-checked local publication recovery."""

    transaction_id: str
    action: Literal[
        "aborted-before-swap",
        "restored-previous",
        "finalized-published",
        "confirmed-published",
    ]


OPTIONAL_ARTIFACTS = [
    ("executive_report.html", "Executive HTML report"),
    ("management_pack.xlsx", "Excel management pack"),
    ("review_register.xlsx", "Exception review register"),
    ("dashboard.html", "Static dashboard"),
    ("summary.md", "Markdown summary"),
    ("evidence/index.html", "Evidence binder index"),
    ("evidence/evidence_register.xlsx", "Evidence register"),
    ("evidence/evidence_index.json", "Evidence JSON index"),
    ("evidence/evidence_manifest.json", "Evidence integrity manifest"),
]
TEXT_SUFFIXES = {".csv", ".html", ".htm", ".json", ".md", ".txt", ".yml", ".yaml"}
RAW_RECORD_NAMES = {"source_records.csv", "match_candidates.csv", "audit_trail.json", "triggered_rules.yml"}
NAME_KEY_HINTS = {
    "customer",
    "supplier",
    "employee",
    "engineer",
    "reviewer",
    "created_by",
    "received_by",
    "equipment",
    "serial",
    "technician",
    "owner",
}
AMOUNT_KEY_HINTS = {
    "amount",
    "cost",
    "price",
    "debit",
    "credit",
    "value",
    "total",
    "balance",
    "standard_cost",
    "unit_cost",
}
MONEY_PATTERN = re.compile(
    r"(?<![\w.-])(?:(?:USD|EUR|GBP|AED|SAR|EGP)\s*[-+]?\d+(?:,\d{3})*(?:\.\d+)?|[-+]?(?:\d{1,3}(?:,\d{3})+|\d+\.\d{2}))(?![\w.-])",
)
LABELED_NAME_PATTERN = re.compile(
    r"\b(Customer|Supplier|Employee|Engineer|Reviewer|Equipment|Serial|Created by|Received by)\s*[:=]\s*([^<\n,;]+?)(?=\s+(?:USD|EUR|GBP|AED|SAR|EGP)\b|\s+[-+]?\d|[<\n,;]|$)",
    re.IGNORECASE,
)


def _is_hidden_or_system(path: Path) -> bool:
    return any(part.startswith(".") or part in {"__pycache__"} for part in path.parts)


def _validated_output_path(source_root: Path, output_path: Path | str) -> Path:
    output_dir = Path(output_path)
    source_resolved = source_root.resolve()
    output_resolved = output_dir.resolve()
    evidence_resolved = (source_resolved / "evidence").resolve()
    if (
        output_resolved == source_resolved
        or source_resolved.is_relative_to(output_resolved)
        or output_resolved.is_relative_to(evidence_resolved)
    ):
        raise ValueError("Client pack output directory must be separate from the source output folder.")
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise ValueError("Client pack output path is invalid")
    return output_dir


def _create_staging_dir(output_dir: Path) -> Path:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        mkdtemp(
            dir=output_dir.parent,
            prefix=f".{output_dir.name}.staging-",
        )
    )


def _publication_siblings(output_dir: Path, kind: str) -> list[Path]:
    output_dir = output_dir.resolve()
    prefix = f".{output_dir.name}.{kind}-"
    return sorted(
        (path for path in output_dir.parent.iterdir() if path.name.startswith(prefix)),
        key=lambda path: path.name,
    )


def _ensure_expected_publication_siblings(
    output_dir: Path,
    *,
    staging_dir: Path,
    rollback_dir: Path | None,
    marker_path: Path | None,
) -> None:
    expected = {
        staging_dir.absolute(),
        *(() if rollback_dir is None else (rollback_dir.absolute(),)),
        *(() if marker_path is None else (marker_path.absolute(),)),
    }
    found = {
        *_publication_siblings(output_dir, "staging"),
        *_publication_siblings(output_dir, "rollback"),
        *_publication_siblings(output_dir, "client-pack-transaction"),
    }
    if found != {path for path in expected if path.exists()}:
        raise ValueError("Client pack publication recovery state is ambiguous")


def _directory_tree_digest(root: Path) -> str:
    files = _bounded_tree_files(root, include_hidden=True)
    if len(files) > CLIENT_PACK_MAX_SOURCE_FILES + _CLIENT_PACK_GENERATED_FILE_ALLOWANCE:
        raise ValueError("Client pack publication directory exceeds the recovery file limit")
    records: list[dict[str, object]] = []
    total_bytes = 0
    for path in sorted(files, key=lambda candidate: candidate.relative_to(root).as_posix()):
        size_bytes = _validate_bounded_source_file(path)
        total_bytes += size_bytes
        if total_bytes > CLIENT_PACK_MAX_TOTAL_SOURCE_BYTES + _CLIENT_PACK_GENERATED_BYTE_ALLOWANCE:
            raise ValueError("Client pack publication directory exceeds the recovery byte limit")
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": size_bytes,
                "sha256": _sha256(path),
            }
        )
    return _canonical_digest(records)


def _publication_marker_payload(
    *,
    transaction_id: str,
    output_dir: Path,
    staging_dir: Path,
    rollback_dir: Path,
    phase: str,
    previous_tree_digest: str,
    staged_tree_digest: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": _PUBLICATION_MARKER_SCHEMA_VERSION,
        "artifact_type": _PUBLICATION_MARKER_ARTIFACT_TYPE,
        "transaction_id": transaction_id,
        "output_name": output_dir.name,
        "staging_name": staging_dir.name,
        "rollback_name": rollback_dir.name,
        "phase": phase,
        "previous_tree_digest": previous_tree_digest,
        "staged_tree_digest": staged_tree_digest,
        "integrity_boundary": _PUBLICATION_MARKER_INTEGRITY_BOUNDARY,
    }
    payload["marker_digest"] = _canonical_digest(payload)
    return payload


def _write_publication_marker(path: Path, payload: dict[str, object]) -> None:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _remove_publication_marker(path: Path) -> None:
    with suppress(FileNotFoundError):
        path.unlink()


def _validate_publication_marker(output_dir: Path, path: Path) -> dict[str, object]:
    if _path_is_reparse(path):
        raise ValueError("Client pack publication marker is invalid")
    try:
        document = read_json_document(path)
    except (OSError, StructuredDocumentError) as exc:
        raise ValueError("Client pack publication marker is invalid") from exc
    if not isinstance(document, dict):
        raise ValueError("Client pack publication marker is invalid")
    required_keys = {
        "schema_version",
        "artifact_type",
        "transaction_id",
        "output_name",
        "staging_name",
        "rollback_name",
        "phase",
        "previous_tree_digest",
        "staged_tree_digest",
        "integrity_boundary",
        "marker_digest",
    }
    if set(document) != required_keys:
        raise ValueError("Client pack publication marker is invalid")
    transaction_id = document.get("transaction_id")
    phase = document.get("phase")
    digests = (
        document.get("previous_tree_digest"),
        document.get("staged_tree_digest"),
        document.get("marker_digest"),
    )
    if (
        document.get("schema_version") != _PUBLICATION_MARKER_SCHEMA_VERSION
        or document.get("artifact_type") != _PUBLICATION_MARKER_ARTIFACT_TYPE
        or document.get("integrity_boundary") != _PUBLICATION_MARKER_INTEGRITY_BOUNDARY
        or not isinstance(transaction_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None
        or phase not in _PUBLICATION_MARKER_PHASES
        or not all(isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) for value in digests)
    ):
        raise ValueError("Client pack publication marker is invalid")
    staging_name = document.get("staging_name")
    expected_names = {
        "output_name": output_dir.name,
        "rollback_name": f".{output_dir.name}.rollback-{transaction_id}",
    }
    if (
        any(document.get(key) != value for key, value in expected_names.items())
        or not isinstance(staging_name, str)
        or not staging_name.startswith(f".{output_dir.name}.staging-")
        or Path(staging_name).name != staging_name
        or "/" in staging_name
        or "\\" in staging_name
    ):
        raise ValueError("Client pack publication marker is invalid")
    expected_marker_name = f".{output_dir.name}.client-pack-transaction-{transaction_id}.json"
    if path.name != expected_marker_name:
        raise ValueError("Client pack publication marker is invalid")
    unsigned = {key: value for key, value in document.items() if key != "marker_digest"}
    marker_digest = document["marker_digest"]
    if not isinstance(marker_digest, str) or not hmac.compare_digest(
        marker_digest,
        _canonical_digest(unsigned),
    ):
        raise ValueError("Client pack publication marker is invalid")
    return document


def _staging_is_bound_to_valid_transaction(staging_dir: Path, output_dir: Path) -> bool:
    for marker_path in _publication_siblings(output_dir, "client-pack-transaction"):
        if not marker_path.name.endswith(".json"):
            continue
        try:
            marker = _validate_publication_marker(output_dir, marker_path)
        except ValueError:
            continue
        if marker["staging_name"] == staging_dir.name:
            return True
    return False


def _publish_staged_output(staging_dir: Path, output_dir: Path) -> None:
    if not output_dir.exists():
        _ensure_expected_publication_siblings(
            output_dir,
            staging_dir=staging_dir,
            rollback_dir=None,
            marker_path=None,
        )
        staging_dir.replace(output_dir)
        return
    transaction_id = secrets.token_hex(16)
    backup_dir = output_dir.parent / f".{output_dir.name}.rollback-{transaction_id}"
    marker_path = output_dir.parent / f".{output_dir.name}.client-pack-transaction-{transaction_id}.json"
    _ensure_expected_publication_siblings(
        output_dir,
        staging_dir=staging_dir,
        rollback_dir=None,
        marker_path=None,
    )
    previous_tree_digest = _directory_tree_digest(output_dir)
    staged_tree_digest = _directory_tree_digest(staging_dir)
    marker = _publication_marker_payload(
        transaction_id=transaction_id,
        output_dir=output_dir,
        staging_dir=staging_dir,
        rollback_dir=backup_dir,
        phase="prepared",
        previous_tree_digest=previous_tree_digest,
        staged_tree_digest=staged_tree_digest,
    )
    _write_publication_marker(marker_path, marker)
    try:
        output_dir.replace(backup_dir)
        marker = {**marker, "phase": "previous-moved"}
        marker["marker_digest"] = _canonical_digest(
            {key: value for key, value in marker.items() if key != "marker_digest"}
        )
        _write_publication_marker(marker_path, marker)
        staging_dir.replace(output_dir)
        marker = {**marker, "phase": "published"}
        marker["marker_digest"] = _canonical_digest(
            {key: value for key, value in marker.items() if key != "marker_digest"}
        )
        _write_publication_marker(marker_path, marker)
    except Exception:
        if output_dir.exists() and not staging_dir.exists() and backup_dir.exists():
            output_dir.replace(staging_dir)
        if backup_dir.exists() and not output_dir.exists():
            backup_dir.replace(output_dir)
        marker = {**marker, "phase": "prepared"}
        marker["marker_digest"] = _canonical_digest(
            {key: value for key, value in marker.items() if key != "marker_digest"}
        )
        _write_publication_marker(marker_path, marker)
        _remove_publication_marker(marker_path)
        raise
    try:
        rmtree(backup_dir)
    except Exception:
        output_dir.replace(staging_dir)
        backup_dir.replace(output_dir)
        marker = {**marker, "phase": "prepared"}
        marker["marker_digest"] = _canonical_digest(
            {key: value for key, value in marker.items() if key != "marker_digest"}
        )
        _write_publication_marker(marker_path, marker)
        _remove_publication_marker(marker_path)
        raise
    _remove_publication_marker(marker_path)


def recover_client_pack_publication(output_path: Path | str) -> ClientPackPublicationRecovery:
    """Explicitly recover one bounded, self-validating interrupted local publication."""

    output_dir = Path(output_path)
    if (
        not output_dir.name
        or not output_dir.parent.is_dir()
        or _path_is_reparse(output_dir)
        or (output_dir.exists() and not output_dir.is_dir())
    ):
        raise ValueError("Client pack publication recovery output is invalid")
    marker_candidates = _publication_siblings(output_dir, "client-pack-transaction")
    if len(marker_candidates) != 1 or _path_is_reparse(marker_candidates[0]):
        raise ValueError("Client pack publication recovery requires exactly one valid marker")
    marker_path = marker_candidates[0]
    marker = _validate_publication_marker(output_dir, marker_path)
    transaction_id = str(marker["transaction_id"])
    staging_dir = output_dir.parent / str(marker["staging_name"])
    rollback_dir = output_dir.parent / str(marker["rollback_name"])
    _ensure_expected_publication_siblings(
        output_dir,
        staging_dir=staging_dir,
        rollback_dir=rollback_dir,
        marker_path=marker_path,
    )
    for path in (staging_dir, rollback_dir):
        if _path_is_reparse(path) or (path.exists() and not path.is_dir()):
            raise ValueError("Client pack publication recovery state is invalid")
    state = (output_dir.exists(), staging_dir.exists(), rollback_dir.exists())
    phase = marker["phase"]
    previous_digest = str(marker["previous_tree_digest"])
    staged_digest = str(marker["staged_tree_digest"])
    action: Literal[
        "aborted-before-swap",
        "restored-previous",
        "finalized-published",
        "confirmed-published",
    ]
    if state == (True, True, False) and phase == "prepared":
        if (
            _directory_tree_digest(output_dir) != previous_digest
            or _directory_tree_digest(staging_dir) != staged_digest
        ):
            raise ValueError("Client pack publication recovery tree digest mismatch")
        rmtree(staging_dir)
        _remove_publication_marker(marker_path)
        action = "aborted-before-swap"
    elif state == (False, True, True) and phase in {"prepared", "previous-moved"}:
        if (
            _directory_tree_digest(rollback_dir) != previous_digest
            or _directory_tree_digest(staging_dir) != staged_digest
        ):
            raise ValueError("Client pack publication recovery tree digest mismatch")
        rollback_dir.replace(output_dir)
        rmtree(staging_dir)
        _remove_publication_marker(marker_path)
        action = "restored-previous"
    elif state == (True, False, True) and phase in {"previous-moved", "published"}:
        if (
            _directory_tree_digest(rollback_dir) != previous_digest
            or _directory_tree_digest(output_dir) != staged_digest
        ):
            raise ValueError("Client pack publication recovery tree digest mismatch")
        rmtree(rollback_dir)
        _remove_publication_marker(marker_path)
        action = "finalized-published"
    elif state == (True, False, False) and phase == "published":
        if _directory_tree_digest(output_dir) != staged_digest:
            raise ValueError("Client pack publication recovery tree digest mismatch")
        _remove_publication_marker(marker_path)
        action = "confirmed-published"
    else:
        raise ValueError("Client pack publication recovery state is ambiguous")
    return ClientPackPublicationRecovery(transaction_id=transaction_id, action=action)


def _key_matches(key: str, hints: set[str]) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(hint in normalized for hint in hints)


def _bucket_amount(
    value: object,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> str:
    try:
        amount = abs(
            parse_amount(
                value,
                input_policy=financial_input_policy,
            )
        )
    except InvalidAmountError:
        return "[AMOUNT_REDACTED]"
    if amount == 0:
        return "0"
    if amount < parse_amount("100", input_policy=STRICT_FINANCIAL_INPUT_POLICY):
        return "0-99"
    if amount < parse_amount("1000", input_policy=STRICT_FINANCIAL_INPUT_POLICY):
        return "100-999"
    if amount < parse_amount("10000", input_policy=STRICT_FINANCIAL_INPUT_POLICY):
        return "1,000-9,999"
    if amount < parse_amount("100000", input_policy=STRICT_FINANCIAL_INPUT_POLICY):
        return "10,000-99,999"
    return "100,000+"


def _redact_value(key: str, value: Any, options: ClientPackOptions) -> Any:
    if options.redact_names and _key_matches(key, NAME_KEY_HINTS):
        return "[REDACTED]"
    if options.redact_amounts and _key_matches(key, AMOUNT_KEY_HINTS):
        return _bucket_amount(
            value,
            financial_input_policy=options.financial_input_policy,
        )
    return value


def _redact_json_object(value: Any, options: ClientPackOptions, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            item_key: _redact_json_object(item_value, options, str(item_key)) for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_json_object(item, options, key) for item in value]
    return _redact_value(key, value, options)


def _redact_text(text: str, options: ClientPackOptions) -> str:
    output = text
    if options.redact_names:
        output = LABELED_NAME_PATTERN.sub(lambda match: f"{match.group(1)}: [REDACTED]", output)
    if options.redact_amounts:
        output = MONEY_PATTERN.sub("[AMOUNT_REDACTED]", output)
    return output


def _source_rejection(code: str, cause: BaseException | None = None) -> FileIngressError:
    rejection = FileIngressError(code)
    if cause is not None:
        rejection.__cause__ = cause
    return rejection


def _path_is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValueError("Client pack publication path is unreadable") from exc
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(file_attributes & reparse_attribute)


def _validate_bounded_source_file(source: Path) -> int:
    try:
        metadata = source.lstat()
    except OSError as exc:
        raise _source_rejection("file_unreadable", exc) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise _source_rejection("file_not_regular")
    if metadata.st_size > CLIENT_PACK_MAX_FILE_BYTES:
        raise _source_rejection("file_size_limit")
    return metadata.st_size


def _validate_bounded_source_set(
    paths: list[Path],
    *,
    max_files: int | None = None,
    max_total_bytes: int | None = None,
) -> None:
    if max_files is None:
        max_files = CLIENT_PACK_MAX_SOURCE_FILES
    if max_total_bytes is None:
        max_total_bytes = CLIENT_PACK_MAX_TOTAL_SOURCE_BYTES
    if len(paths) > max_files:
        raise _source_rejection("file_count_limit")
    total_bytes = 0
    for source in paths:
        total_bytes += _validate_bounded_source_file(source)
        if total_bytes > max_total_bytes:
            raise _source_rejection("file_total_size_limit")


def _stream_redacted_text(
    source: Path,
    options: ClientPackOptions,
    target_handle: Any | None = None,
) -> None:
    _validate_bounded_source_file(source)
    try:
        with source.open(
            "r",
            encoding="utf-8",
            errors="strict",
            newline="",
        ) as source_handle:
            while True:
                line = source_handle.readline(CLIENT_PACK_MAX_TEXT_LINE_CHARACTERS + 1)
                if not line:
                    break
                if len(line) > CLIENT_PACK_MAX_TEXT_LINE_CHARACTERS:
                    raise _source_rejection("text_line_limit")
                if target_handle is not None:
                    target_handle.write(_redact_text(line, options))
    except FileIngressError:
        raise
    except UnicodeError as exc:
        raise _source_rejection("text_encoding_invalid", exc) from exc
    except OSError as exc:
        raise _source_rejection("file_unreadable", exc) from exc


def _validate_redaction_text(source: Path, options: ClientPackOptions) -> None:
    try:
        _stream_redacted_text(source, options)
    except FileIngressError as exc:
        raise ValueError("Client pack text redaction input is invalid") from exc


def _redact_text_file(
    source: Path,
    target: Path,
    options: ClientPackOptions,
) -> None:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as target_handle:
            temporary_path = Path(target_handle.name)
            _stream_redacted_text(source, options, target_handle)
        temporary_path.replace(target)
        temporary_path = None
    except FileIngressError as exc:
        raise ValueError("Client pack text redaction input is invalid") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _copy_bounded_file(source: Path, target: Path) -> None:
    expected_size = _validate_bounded_source_file(source)
    temporary_path: Path | None = None
    try:
        with source.open("rb") as source_handle:
            opened_size = os.fstat(source_handle.fileno()).st_size
            if opened_size != expected_size or opened_size > CLIENT_PACK_MAX_FILE_BYTES:
                raise _source_rejection("file_changed_during_read")
            with NamedTemporaryFile(
                "wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as target_handle:
                temporary_path = Path(target_handle.name)
                copied = 0
                while chunk := source_handle.read(_CLIENT_PACK_IO_CHUNK_BYTES):
                    copied += len(chunk)
                    if copied > CLIENT_PACK_MAX_FILE_BYTES:
                        raise _source_rejection("file_size_limit")
                    target_handle.write(chunk)
                if copied != expected_size or os.fstat(source_handle.fileno()).st_size != expected_size:
                    raise _source_rejection("file_changed_during_read")
        temporary_path.replace(target)
        temporary_path = None
    except FileIngressError as exc:
        raise ValueError("Client pack source input is invalid") from exc
    except OSError as exc:
        raise ValueError("Client pack source input is invalid") from _source_rejection(
            "file_unreadable",
            exc,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _validate_redaction_csv(source: Path) -> tuple[str, ...]:
    try:
        validate_tabular_input(source)
        with source.open(
            "r",
            encoding="utf-8",
            errors="strict",
            newline="",
        ) as handle:
            fieldnames = tuple(csv.DictReader(handle, strict=True).fieldnames or ())
        if len(fieldnames) != len(set(fieldnames)):
            raise FileIngressError("csv_header_duplicate")
    except FileIngressError as exc:
        raise ValueError("Client pack CSV redaction input is invalid") from exc
    except (OSError, UnicodeError, csv.Error) as exc:
        rejection = FileIngressError("csv_structure_invalid")
        rejection.__cause__ = exc
        raise ValueError("Client pack CSV redaction input is invalid") from rejection
    return fieldnames


def _redact_csv_file(source: Path, target: Path, options: ClientPackOptions) -> None:
    expected_fieldnames = _validate_redaction_csv(source)
    temporary_path: Path | None = None
    try:
        with source.open(
            "r",
            encoding="utf-8",
            errors="strict",
            newline="",
        ) as source_handle:
            reader = csv.DictReader(source_handle, strict=True)
            if tuple(reader.fieldnames or ()) != expected_fieldnames:
                raise csv.Error("CSV header changed after validation")
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as target_handle:
                temporary_path = Path(target_handle.name)
                writer = csv.DictWriter(
                    target_handle,
                    fieldnames=list(expected_fieldnames),
                )
                writer.writeheader()
                for row in reader:
                    redacted: dict[str, Any] = {}
                    for key in expected_fieldnames:
                        value = row.get(key)
                        if value is None:
                            raise csv.Error("CSV shape changed after validation")
                        redacted[key] = _redact_value(key, value, options)
                    writer.writerow(redacted)
        temporary_path.replace(target)
        temporary_path = None
    except (OSError, UnicodeError, csv.Error) as exc:
        rejection = FileIngressError("csv_structure_invalid")
        rejection.__cause__ = exc
        raise ValueError("Client pack CSV redaction input is invalid") from rejection
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _read_redaction_json(source: Path, options: ClientPackOptions) -> object:
    try:
        return read_json_document(
            source,
            preserve_float_lexemes=(options.financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY),
        )
    except StructuredDocumentError as exc:
        raise ValueError("Client pack JSON redaction input is invalid") from exc


def _redact_json_file(source: Path, target: Path, options: ClientPackOptions) -> None:
    payload = _read_redaction_json(source, options)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(_redact_json_object(payload, options), handle, indent=2, default=json_default)


def _copy_with_controls(source: Path, target: Path, options: ClientPackOptions) -> Path | None:
    if options.redaction_requested and source.suffix.lower() not in TEXT_SUFFIXES:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if not options.redaction_requested:
        _copy_bounded_file(source, target)
        return target
    suffix = source.suffix.lower()
    if suffix == ".csv":
        _redact_csv_file(source, target, options)
    elif suffix == ".json":
        _redact_json_file(source, target, options)
    else:
        _redact_text_file(source, target, options)
    return target


def _should_exclude(relative: Path, options: ClientPackOptions) -> str | None:
    if options.summary_only and relative.as_posix() != "summary.md":
        return "excluded by --summary-only"
    if options.exclude_evidence and relative.parts and relative.parts[0] == "evidence":
        return "excluded by --exclude-evidence"
    if options.exclude_raw_records and relative.name in RAW_RECORD_NAMES:
        return "excluded by --exclude-raw-records"
    return None


def _copy_optional_file(
    source_root: Path,
    output_root: Path,
    relative_name: str,
    options: ClientPackOptions,
    target_relative_name: str | None = None,
    candidate_sources: frozenset[Path] | None = None,
) -> tuple[Path | None, str | None]:
    relative = Path(relative_name)
    excluded_reason = _should_exclude(relative, options)
    if excluded_reason is not None:
        return None, f"{relative.as_posix()} ({excluded_reason})"
    source = source_root / relative_name
    if candidate_sources is not None and source not in candidate_sources:
        return None, None
    if not source.exists() or not source.is_file() or _is_hidden_or_system(Path(relative_name)):
        return None, None
    target = output_root / (target_relative_name or relative_name)
    copied = _copy_with_controls(source, target, options)
    if copied is None:
        return None, f"{relative.as_posix()} (excluded because redaction is not supported for this file type)"
    return copied, None


def _copy_evidence_folder(
    source_root: Path,
    output_root: Path,
    options: ClientPackOptions,
    candidate_sources: frozenset[Path],
) -> tuple[list[Path], list[str]]:
    if options.summary_only or options.exclude_evidence:
        return [], [
            "evidence/ (excluded by --summary-only)"
            if options.summary_only
            else "evidence/ (excluded by --exclude-evidence)"
        ]
    evidence_root = source_root / "evidence"
    if not evidence_root.exists() or not evidence_root.is_dir():
        return [], []
    copied: list[Path] = []
    excluded: list[str] = []
    for source in sorted(path for path in candidate_sources if path.is_relative_to(evidence_root)):
        relative = source.relative_to(source_root)
        if _is_hidden_or_system(relative):
            continue
        excluded_reason = _should_exclude(relative, options)
        if excluded_reason is not None:
            excluded.append(f"{relative.as_posix()} ({excluded_reason})")
            continue
        target = output_root / relative
        copied_path = _copy_with_controls(source, target, options)
        if copied_path is None:
            excluded.append(f"{relative.as_posix()} (excluded because redaction is not supported for this file type)")
            continue
        copied.append(copied_path)
    return copied, excluded


def _write_pack_text(
    output_dir: Path,
    input_path: Path,
    included: list[Path],
    missing: list[str],
    excluded: list[str],
    options: ClientPackOptions,
) -> tuple[Path, Path, Path]:
    source_label = (
        "[local path omitted]" if options.financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY else str(input_path)
    )
    summary_path = output_dir / "handoff_summary.md"
    summary_path.write_text(
        "\n".join(
            [
                "# ReconForge Client Handoff Summary",
                "",
                f"Source output folder: `{source_label}`",
                "",
                "Included artifacts:",
                *[f"- `{path.relative_to(output_dir).as_posix()}`" for path in included],
                "",
                "Missing optional artifacts:",
                *([f"- `{name}`" for name in missing] if missing else ["- none"]),
                "",
                "Excluded artifacts:",
                *([f"- `{name}`" for name in excluded] if excluded else ["- none"]),
                "",
                "Sharing controls:",
                f"- redact_names: `{options.redact_names}`",
                f"- redact_amounts: `{options.redact_amounts}`",
                f"- exclude_raw_records: `{options.exclude_raw_records}`",
                f"- summary_only: `{options.summary_only}`",
                f"- exclude_evidence: `{options.exclude_evidence}`",
                f"- include_manifest_checksums: `{options.include_manifest_checksums}`",
                f"- financial_input_policy: `{options.financial_input_policy}`",
                "",
                "Use this pack to review generated reports, exception review status, evidence status, and next actions with finance, audit, ERP, and operations stakeholders.",
                "",
                "Prepared/reviewed and certification fields, when present, are local workflow metadata only. They are not a legal sign-off, audit opinion, compliance certification, or digital signature.",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    next_steps_path = output_dir / "next_steps.md"
    next_steps_path.write_text(
        "\n".join(
            [
                "# Recommended Next Steps",
                "",
                "1. Review high and critical exceptions first.",
                "2. Assign each exception to a reviewer and local review status.",
                "3. Document accepted risks with a reason and owner.",
                "4. Escalate unresolved posting, WIP, or evidence gaps before close or audit sign-off.",
                "5. Rerun ReconForge after source corrections or updated ERP exports.",
                "6. Regenerate this pack after review-state or source-data changes.",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    privacy_note_path = output_dir / "data_privacy_note.md"
    privacy_note_path.write_text(
        "\n".join(
            [
                "# Data Privacy Note",
                "",
                "This handoff pack was generated locally from ReconForge outputs. Core ReconForge workflows do not require cloud upload, SaaS authentication, or an external database.",
                "",
                "Before sharing this folder outside the company or engagement team, review every included file for ERP exports, source records, customer names, supplier names, employee names, equipment identifiers, and monetary values.",
                "",
                "If redaction options were used, they were applied only to files copied into this client pack. The original ReconForge output folder was not modified. Binary workbooks are excluded when redaction is requested because text-level redaction cannot safely rewrite every workbook cell.",
                "",
                "Evidence folders may contain generated source-record extracts intended for audit review. Treat them as sensitive unless the client or engagement owner confirms they can be shared.",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    return summary_path, next_steps_path, privacy_note_path


def _sha256(path: Path) -> str:
    expected_size = _validate_bounded_source_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        if os.fstat(handle.fileno()).st_size != expected_size:
            raise _source_rejection("file_changed_during_read")
        total = 0
        for chunk in iter(lambda: handle.read(_CLIENT_PACK_IO_CHUNK_BYTES), b""):
            total += len(chunk)
            if total > CLIENT_PACK_MAX_FILE_BYTES:
                raise _source_rejection("file_size_limit")
            digest.update(chunk)
        if total != expected_size or os.fstat(handle.fileno()).st_size != expected_size:
            raise _source_rejection("file_changed_during_read")
    return digest.hexdigest()


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_tree_files(root: Path, *, include_hidden: bool = False) -> list[Path]:
    if _path_is_reparse(root):
        raise ValueError("Client pack source input is invalid") from _source_rejection("file_not_regular")
    stack = [root]
    files: list[Path] = []
    entries_seen = 0
    try:
        while stack:
            directory = stack.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    entries_seen += 1
                    if entries_seen > CLIENT_PACK_MAX_DIRECTORY_ENTRIES:
                        raise _source_rejection("directory_entry_limit")
                    relative = Path(entry.path).relative_to(root)
                    if not include_hidden and _is_hidden_or_system(relative):
                        continue
                    if entry.is_symlink():
                        raise _source_rejection("file_not_regular")
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        files.append(Path(entry.path))
                    else:
                        raise _source_rejection("file_not_regular")
    except FileIngressError as exc:
        raise ValueError("Client pack source input is invalid") from exc
    except OSError as exc:
        raise ValueError("Client pack source input is invalid") from _source_rejection(
            "file_unreadable",
            exc,
        )
    return files


def _bounded_evidence_files(evidence_root: Path) -> list[Path]:
    return _bounded_tree_files(evidence_root)


def _candidate_source_files(source_root: Path) -> list[Path]:
    candidates = [source_root / name for name, _description in OPTIONAL_ARTIFACTS]
    evidence_root = source_root / "evidence"
    if evidence_root.exists() and evidence_root.is_dir():
        candidates.extend(_bounded_evidence_files(evidence_root))
    unique: dict[str, Path] = {}
    for source in candidates:
        if not source.exists() or not source.is_file():
            continue
        relative = source.relative_to(source_root)
        if _is_hidden_or_system(relative):
            continue
        unique[relative.as_posix()] = source
    return [unique[name] for name in sorted(unique)]


def _selected_source_files(
    source_root: Path,
    options: ClientPackOptions,
    *,
    candidates: list[Path] | None = None,
) -> list[Path]:
    if candidates is None:
        candidates = _candidate_source_files(source_root)
    selected: dict[str, Path] = {}
    for source in candidates:
        relative = source.relative_to(source_root)
        if _should_exclude(relative, options) is not None:
            continue
        if options.redaction_requested and source.suffix.lower() not in TEXT_SUFFIXES:
            continue
        selected[relative.as_posix()] = source
    return [selected[name] for name in sorted(selected)]


def _file_fingerprints(
    root: Path,
    paths: list[Path],
    *,
    max_files: int | None = None,
    max_total_bytes: int | None = None,
) -> list[dict[str, Any]]:
    if max_files is None:
        max_files = CLIENT_PACK_MAX_SOURCE_FILES + _CLIENT_PACK_GENERATED_FILE_ALLOWANCE
    if max_total_bytes is None:
        max_total_bytes = CLIENT_PACK_MAX_TOTAL_SOURCE_BYTES + _CLIENT_PACK_GENERATED_BYTE_ALLOWANCE
    _validate_bounded_source_set(
        paths,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
    )
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in paths
    ]


def _preflight_copy_inputs(paths: list[Path], options: ClientPackOptions) -> None:
    """Reject unsafe selected inputs before destination mutation."""

    if options.redaction_requested:
        for source in paths:
            suffix = source.suffix.lower()
            if suffix == ".csv":
                _validate_redaction_csv(source)
            elif suffix == ".json":
                _read_redaction_json(source, options)
            else:
                _validate_redaction_text(source, options)
    try:
        _validate_bounded_source_set(paths)
    except FileIngressError as exc:
        raise ValueError("Client pack source input is invalid") from exc


def _redaction_settings(options: ClientPackOptions) -> dict[str, bool]:
    return {
        "redact_names": options.redact_names,
        "redact_amounts": options.redact_amounts,
        "exclude_raw_records": options.exclude_raw_records,
        "summary_only": options.summary_only,
        "exclude_evidence": options.exclude_evidence,
        "include_manifest_checksums": options.include_manifest_checksums,
    }


def _current_redaction_policy() -> dict[str, Any]:
    return {
        "algorithm_version": CLIENT_PACK_REDACTION_ALGORITHM_VERSION,
        "json_decimal_policy": "preserve-lexeme-as-text-v2",
        "amount_bucket_boundaries": ["0", "100", "1000", "10000", "100000"],
        "invalid_amount_policy": "full-redaction-token-v1",
        "output_checksum_policy": "required-v2",
    }


def _current_content_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": CLIENT_PACK_MANIFEST_SCHEMA_VERSION,
        "artifact_type": _CLIENT_PACK_ARTIFACT_TYPE,
        "tool_version": payload.get("tool_version"),
        "financial_input_policy": payload.get("financial_input_policy"),
        "redaction_policy": payload.get("redaction_policy"),
        "input_files": payload.get("input_files"),
        "redaction_settings": payload.get("redaction_settings"),
        "included_files": payload.get("included_files"),
        "missing_optional_files": payload.get("missing_optional_files"),
        "excluded_files": payload.get("excluded_files"),
        "integrity_boundary": payload.get("integrity_boundary"),
    }


def _write_manifest(
    output_dir: Path,
    input_path: Path,
    included: list[Path],
    missing: list[str],
    excluded: list[str],
    options: ClientPackOptions,
    *,
    input_files: list[dict[str, Any]],
) -> Path:
    manifest_path = output_dir / "files_manifest.json"
    included_files = [
        {
            "path": path.relative_to(output_dir).as_posix(),
            "size_bytes": path.stat().st_size,
            **(
                {"sha256": _sha256(path)}
                if options.financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY or options.include_manifest_checksums
                else {}
            ),
        }
        for path in sorted(set(included))
        if path.exists() and path.is_file()
    ]
    common_payload: dict[str, Any] = {
        "generated_at": utc_now_text(),
        "tool_version": __version__,
        "source_output_folder": (
            "[local path omitted]"
            if options.financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY
            else str(input_path)
        ),
        "local_first_note": "Generated from local ReconForge outputs; review before external sharing.",
        "privacy_note": "Client packs may contain sensitive generated report content. Review before sharing outside the authorized team.",
        "redaction_settings": _redaction_settings(options),
        "included_files": included_files,
        "missing_optional_files": missing,
        "excluded_files": excluded,
    }
    payload: dict[str, Any]
    if options.financial_input_policy == LEGACY_FINANCIAL_INPUT_POLICY:
        payload = common_payload
    else:
        payload = {
            "schema_version": CLIENT_PACK_MANIFEST_SCHEMA_VERSION,
            "artifact_type": _CLIENT_PACK_ARTIFACT_TYPE,
            "financial_input_policy": options.financial_input_policy,
            "redaction_policy": _current_redaction_policy(),
            "input_files": input_files,
            "integrity_boundary": _CLIENT_PACK_INTEGRITY_BOUNDARY,
            **common_payload,
        }
        payload["content_digest"] = _canonical_digest(_current_content_payload(payload))
        payload["artifact_digest"] = _canonical_digest(payload)
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=json_default)
    return manifest_path


def generate_client_pack(
    input_path: Path | str,
    output_path: Path | str,
    *,
    redact_names: bool = False,
    redact_amounts: bool = False,
    exclude_raw_records: bool = False,
    summary_only: bool = False,
    exclude_evidence: bool = False,
    include_manifest_checksums: bool = False,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> ClientPackArtifacts:
    """Create a local client handoff folder from generated ReconForge outputs."""

    input_policy = validate_financial_input_policy(financial_input_policy)
    source_root = Path(input_path)
    if source_root.is_symlink() or not source_root.exists() or not source_root.is_dir():
        raise FileNotFoundError(f"Generated output directory does not exist: {source_root}")
    output_dir = _validated_output_path(source_root, output_path)
    options = ClientPackOptions(
        redact_names=redact_names,
        redact_amounts=redact_amounts,
        exclude_raw_records=exclude_raw_records,
        summary_only=summary_only,
        exclude_evidence=exclude_evidence,
        include_manifest_checksums=include_manifest_checksums,
        financial_input_policy=input_policy,
    )
    source_candidates = _candidate_source_files(source_root)
    candidate_sources = frozenset(source_candidates)
    source_files = _selected_source_files(
        source_root,
        options,
        candidates=source_candidates,
    )
    _preflight_copy_inputs(source_files, options)
    try:
        input_files = _file_fingerprints(
            source_root,
            source_files,
            max_files=CLIENT_PACK_MAX_SOURCE_FILES,
            max_total_bytes=CLIENT_PACK_MAX_TOTAL_SOURCE_BYTES,
        )
    except FileIngressError as exc:
        raise ValueError("Client pack source input is invalid") from exc
    staging_dir = _create_staging_dir(output_dir)
    try:
        included: list[Path] = []
        missing: list[str] = []
        excluded: list[str] = []
        for relative_name, _description in OPTIONAL_ARTIFACTS:
            target_relative_name = "source_summary.md" if relative_name == "summary.md" else None
            copied, excluded_reason = _copy_optional_file(
                source_root,
                staging_dir,
                relative_name,
                options,
                target_relative_name,
                candidate_sources,
            )
            if copied is None:
                if excluded_reason is None:
                    missing.append(relative_name)
                else:
                    excluded.append(excluded_reason)
            else:
                included.append(copied)
        evidence_files, evidence_excluded = _copy_evidence_folder(
            source_root,
            staging_dir,
            options,
            candidate_sources,
        )
        for path in evidence_files:
            if path not in included:
                included.append(path)
        excluded.extend(evidence_excluded)

        summary_path, next_steps_path, privacy_note_path = _write_pack_text(
            staging_dir,
            source_root,
            included,
            missing,
            excluded,
            options,
        )
        included.extend([summary_path, next_steps_path, privacy_note_path])
        try:
            final_input_files = _file_fingerprints(
                source_root,
                source_files,
                max_files=CLIENT_PACK_MAX_SOURCE_FILES,
                max_total_bytes=CLIENT_PACK_MAX_TOTAL_SOURCE_BYTES,
            )
        except FileIngressError as exc:
            raise ValueError("Client pack source files changed during generation") from exc
        if final_input_files != input_files:
            raise ValueError("Client pack source files changed during generation")
        manifest_path = _write_manifest(
            staging_dir,
            source_root,
            included,
            missing,
            excluded,
            options,
            input_files=input_files,
        )
        included.append(manifest_path)
        relative_included = [path.relative_to(staging_dir) for path in included]
        relative_manifest = manifest_path.relative_to(staging_dir)
        relative_summary = summary_path.relative_to(staging_dir)
        relative_next_steps = next_steps_path.relative_to(staging_dir)
        relative_privacy_note = privacy_note_path.relative_to(staging_dir)
        _publish_staged_output(staging_dir, output_dir)
    finally:
        if staging_dir.exists() and not _staging_is_bound_to_valid_transaction(
            staging_dir,
            output_dir,
        ):
            rmtree(staging_dir)
    return ClientPackArtifacts(
        output_dir=output_dir,
        included_files=sorted({output_dir / path for path in relative_included}),
        missing_optional_files=missing,
        excluded_files=excluded,
        manifest_path=output_dir / relative_manifest,
        summary_path=output_dir / relative_summary,
        next_steps_path=output_dir / relative_next_steps,
        privacy_note_path=output_dir / relative_privacy_note,
    )


def _require_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Client pack {field_name} must be an object")
    return value


def _require_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Client pack {field_name} must be an array of strings")
    return value


def _safe_manifest_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Client pack manifest contains an unsafe file path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("Client pack manifest contains an unsafe file path")
    return value


def _validate_file_records(
    value: object,
    field_name: str,
    *,
    require_digest: bool,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Client pack {field_name} must be an array of objects")
    records = list(value)
    paths: list[str] = []
    for item in records:
        path = _safe_manifest_path(item.get("path"))
        size_bytes = item.get("size_bytes")
        digest = item.get("sha256")
        allowed_keys = {"path", "size_bytes", "sha256"} if digest is not None else {"path", "size_bytes"}
        if (
            set(item) != allowed_keys
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or (require_digest and (not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None))
            or (digest is not None and (not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None))
        ):
            raise ValueError("Client pack manifest contains an invalid file fingerprint")
        paths.append(path)
    if paths != sorted(set(paths)):
        raise ValueError("Client pack manifest file fingerprints must be unique and sorted")
    return records


def _validated_redaction_settings(value: object) -> dict[str, bool]:
    settings = _require_mapping(value, "redaction_settings")
    expected_keys = {
        "redact_names",
        "redact_amounts",
        "exclude_raw_records",
        "summary_only",
        "exclude_evidence",
        "include_manifest_checksums",
    }
    if set(settings) != expected_keys or not all(isinstance(settings[key], bool) for key in expected_keys):
        raise ValueError("Client pack redaction settings are invalid")
    return {key: settings[key] for key in expected_keys}


def _options_from_manifest(
    settings: dict[str, bool],
    input_policy: FinancialInputPolicy,
) -> ClientPackOptions:
    return ClientPackOptions(
        redact_names=settings["redact_names"],
        redact_amounts=settings["redact_amounts"],
        exclude_raw_records=settings["exclude_raw_records"],
        summary_only=settings["summary_only"],
        exclude_evidence=settings["exclude_evidence"],
        include_manifest_checksums=settings["include_manifest_checksums"],
        financial_input_policy=input_policy,
    )


def verify_client_pack_manifest_payload(
    payload: dict[str, Any],
    *,
    source_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> None:
    """Verify current manifest digests and optionally recheck local bytes."""

    if payload.get("schema_version") != CLIENT_PACK_MANIFEST_SCHEMA_VERSION:
        raise ValueError("Only current v2 client pack manifests are verifiable")
    if payload.get("artifact_type") != _CLIENT_PACK_ARTIFACT_TYPE:
        raise ValueError("Client pack artifact type is invalid")
    input_policy = validate_financial_input_policy(payload.get("financial_input_policy"))
    if input_policy != STRICT_FINANCIAL_INPUT_POLICY:
        raise ValueError("Client pack v2 requires the strict financial input policy")
    if payload.get("redaction_policy") != _current_redaction_policy():
        raise ValueError("Client pack redaction policy is invalid")
    settings = _validated_redaction_settings(payload.get("redaction_settings"))
    input_files = _validate_file_records(
        payload.get("input_files"),
        "input_files",
        require_digest=True,
    )
    included_files = _validate_file_records(
        payload.get("included_files"),
        "included_files",
        require_digest=True,
    )
    _require_string_list(payload.get("missing_optional_files"), "missing_optional_files")
    _require_string_list(payload.get("excluded_files"), "excluded_files")
    if payload.get("integrity_boundary") != _CLIENT_PACK_INTEGRITY_BOUNDARY:
        raise ValueError("Client pack integrity boundary is invalid")
    content_digest = payload.get("content_digest")
    if not isinstance(content_digest, str) or not hmac.compare_digest(
        content_digest,
        _canonical_digest(_current_content_payload(payload)),
    ):
        raise ValueError("Client pack content digest verification failed")
    artifact_digest = payload.get("artifact_digest")
    payload_without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    if not isinstance(artifact_digest, str) or not hmac.compare_digest(
        artifact_digest,
        _canonical_digest(payload_without_digest),
    ):
        raise ValueError("Client pack artifact digest verification failed")
    if source_dir is not None:
        source_root = Path(source_dir)
        options = _options_from_manifest(settings, input_policy)
        current_inputs = _file_fingerprints(
            source_root,
            _selected_source_files(source_root, options),
            max_files=CLIENT_PACK_MAX_SOURCE_FILES,
            max_total_bytes=CLIENT_PACK_MAX_TOTAL_SOURCE_BYTES,
        )
        if input_files != current_inputs:
            raise ValueError("Client pack input fingerprint verification failed")
    if output_dir is not None:
        output_root = Path(output_dir)
        try:
            current_paths = [
                path for path in sorted(_bounded_tree_files(output_root)) if path.name != "files_manifest.json"
            ]
            current_output_files = _file_fingerprints(output_root, current_paths)
        except (FileIngressError, ValueError) as exc:
            raise ValueError("Client pack output fingerprint verification failed") from exc
        if included_files != current_output_files:
            raise ValueError("Client pack output fingerprint verification failed")


def read_client_pack_manifest(path: Path | str) -> ClientPackManifestDocument:
    """Read historical unversioned v1 or verify current schema-v2 manifest."""

    source = Path(path)
    try:
        payload = read_json_document(source)
    except StructuredDocumentError as exc:
        raise ValueError("Client pack manifest JSON is invalid") from exc
    document = _require_mapping(payload, "document")
    _validated_redaction_settings(document.get("redaction_settings"))
    if "schema_version" not in document:
        _validate_file_records(
            document.get("included_files"),
            "included_files",
            require_digest=False,
        )
        return ClientPackManifestDocument(
            schema_version=1,
            verification_status="legacy-unverified",
            payload=document,
        )
    verify_client_pack_manifest_payload(document)
    return ClientPackManifestDocument(
        schema_version=2,
        verification_status="verified",
        payload=document,
    )
