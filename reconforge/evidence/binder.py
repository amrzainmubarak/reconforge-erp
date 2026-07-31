"""Generate audit evidence binders from ReconForge output."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

import pandas as pd

from reconforge import __version__
from reconforge.evidence.index import write_evidence_index_html, write_evidence_register
from reconforge.evidence.models import EvidenceArtifact, EvidenceCase
from reconforge.evidence.templates import business_impact, recommended_action, responsible_department
from reconforge.evidence.writer import write_evidence_case
from reconforge.io.generated import (
    GeneratedCsvDocument,
    GeneratedCsvMode,
    read_generated_csv_document,
    verify_generated_csv_document,
)
from reconforge.io.structured import StructuredDocumentError, read_json_document
from reconforge.io.writers import json_default, write_json
from reconforge.review.state import load_review_state
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
    validate_financial_input_policy,
)
from reconforge.utils.time import utc_now_text

_MAX_RISK_SCORE_CHARS = 100
EVIDENCE_INDEX_SCHEMA_VERSION = 3
EVIDENCE_RISK_SCORE_POLICY = "integer-0-to-100-v1"
_EVIDENCE_INDEX_ARTIFACT_TYPE = "reconforge-evidence-index"
_EVIDENCE_INDEX_INTEGRITY_BOUNDARY = (
    "The content digest covers the exact selected input-file fingerprints, "
    "financial/risk policies, and generated case decisions except generation "
    "timestamps. The artifact digest additionally covers those timestamps and "
    "document metadata. Evidence output bytes remain covered by evidence_manifest.json."
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_GeneratedCsvCache = dict[Path, GeneratedCsvDocument]


@dataclass(frozen=True)
class EvidenceIndexDocument:
    """A historical or current evidence-index document."""

    schema_version: Literal[2, 3]
    verification_status: Literal["legacy-unverified", "verified"]
    payload: dict[str, Any]


@dataclass(frozen=True)
class _ParsedRiskScore:
    value: int | None
    status: Literal["valid", "missing", "invalid"]


def _parse_risk_score(
    value: object,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> _ParsedRiskScore:
    if value is None:
        return _ParsedRiskScore(None, "missing")
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "nat", "none", "null", "n/a", "<na>"}:
        return _ParsedRiskScore(None, "missing")
    if len(text) > _MAX_RISK_SCORE_CHARS:
        return _ParsedRiskScore(None, "invalid")
    try:
        parsed = parse_amount(value, input_policy=financial_input_policy)
    except InvalidAmountError:
        return _ParsedRiskScore(None, "invalid")
    if parsed < 0 or parsed > 100 or parsed != parsed.to_integral_value():
        return _ParsedRiskScore(None, "invalid")
    return _ParsedRiskScore(int(parsed), "valid")


def _risk_score_from_row(
    row: pd.Series,
    *,
    financial_input_policy: FinancialInputPolicy,
) -> _ParsedRiskScore:
    for column in ("risk_score", "risk_impact"):
        if column not in row.index:
            continue
        result = _parse_risk_score(
            row.get(column),
            financial_input_policy=financial_input_policy,
        )
        if result.status != "missing":
            return result
    return _ParsedRiskScore(None, "missing")


def _read_csv_if_exists(
    path: Path,
    *,
    financial_input_policy: FinancialInputPolicy,
    cache: _GeneratedCsvCache | None = None,
) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    mode: GeneratedCsvMode = "exact-text" if financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY else "display"
    document = cache.get(path) if cache is not None else None
    if document is None:
        document = read_generated_csv_document(path, mode=mode)
        if cache is not None:
            cache[path] = document
    elif document.mode != mode:
        raise ValueError("Generated CSV cache representation does not match financial input policy")
    return document.frame


def _candidate_files(input_dir: Path) -> list[Path]:
    preferred = [
        input_dir / "management_pack_stock_gl_all_exceptions.csv",
        input_dir / "management_pack_workorders_all_exceptions.csv",
        input_dir / "stock_gl_all_exceptions.csv",
        input_dir / "workorders_all_exceptions.csv",
    ]
    return [path for path in preferred if path.exists()]


def _risk_filter(
    frame: pd.DataFrame,
    *,
    financial_input_policy: FinancialInputPolicy,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    parsed_scores = [
        _risk_score_from_row(
            row,
            financial_input_policy=financial_input_policy,
        )
        for _, row in frame.iterrows()
    ]
    high_score = pd.Series(
        [result.value is not None and result.value >= 61 for result in parsed_scores],
        index=frame.index,
    )
    invalid_score = pd.Series([result.status == "invalid" for result in parsed_scores], index=frame.index)
    risk_level = frame.get("risk_level", pd.Series([""] * len(frame))).astype(str).str.lower()
    return frame[high_score | invalid_score | risk_level.isin({"high", "critical"})].copy()


def _first_nonempty(row: pd.Series, names: list[str]) -> str | None:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() and str(value).lower() not in {"nan", "none"}:
            return str(value)
    return None


def _string_keyed_record(row: pd.Series) -> dict[str, Any]:
    return {str(key): value for key, value in row.to_dict().items()}


def _match_candidates(
    input_dir: Path,
    row: pd.Series,
    *,
    financial_input_policy: FinancialInputPolicy,
    csv_cache: _GeneratedCsvCache,
) -> list[dict[str, Any]]:
    matched = _read_csv_if_exists(
        input_dir / "stock_gl_matched_transactions.csv",
        financial_input_policy=financial_input_policy,
        cache=csv_cache,
    )
    if matched.empty:
        matched = _read_csv_if_exists(
            input_dir / "management_pack_stock_gl_matched_transactions.csv",
            financial_input_policy=financial_input_policy,
            cache=csv_cache,
        )
    if matched.empty:
        return []
    work_order = _first_nonempty(row, ["work_order", "linked_work_order"])
    source_document = _first_nonempty(row, ["source_document", "reference", "po_number"])
    mask = pd.Series([False] * len(matched))
    if work_order and "work_order" in matched.columns:
        mask = mask | matched["work_order"].astype(str).eq(work_order)
    if source_document:
        for column in ("source_document", "gl_reference"):
            if column in matched.columns:
                mask = mask | matched[column].astype(str).eq(source_document)
    return cast(list[dict[str, Any]], matched[mask].head(10).to_dict(orient="records"))


def _rule_results(
    input_dir: Path,
    row: pd.Series,
    *,
    financial_input_policy: FinancialInputPolicy,
    csv_cache: _GeneratedCsvCache,
) -> list[dict[str, Any]]:
    rules = _read_csv_if_exists(
        input_dir / "rules" / "rule_results.csv",
        financial_input_policy=financial_input_policy,
        cache=csv_cache,
    )
    if rules.empty:
        rules = _read_csv_if_exists(
            input_dir / "rule_results.csv",
            financial_input_policy=financial_input_policy,
            cache=csv_cache,
        )
    if rules.empty:
        return []
    work_order = _first_nonempty(row, ["work_order", "linked_work_order"])
    if work_order and "evidence_fields" in rules.columns:
        return cast(
            list[dict[str, Any]],
            rules[rules["evidence_fields"].astype(str).str.contains(work_order, regex=False)]
            .head(10)
            .to_dict(
                orient="records",
            ),
        )
    return cast(list[dict[str, Any]], rules.head(10).to_dict(orient="records"))


def _case_from_row(
    input_dir: Path,
    row: pd.Series,
    index: int,
    *,
    financial_input_policy: FinancialInputPolicy,
    csv_cache: _GeneratedCsvCache,
) -> EvidenceCase:
    exception_type = _first_nonempty(row, ["exception_type", "rule_name"]) or "unclassified_exception"
    parsed_risk = _risk_score_from_row(
        row,
        financial_input_policy=financial_input_policy,
    )
    declared_severity = _first_nonempty(row, ["risk_level", "severity"])
    if parsed_risk.status == "invalid":
        severity = "Data Quality"
    else:
        severity = declared_severity or (
            "Critical" if parsed_risk.value is not None and parsed_risk.value >= 81 else "High"
        )
    source_file = _first_nonempty(row, ["source_file"]) or "generated_report"
    return EvidenceCase(
        exception_id=f"EXC-{index:04d}",
        exception_type=exception_type,
        severity=severity,
        risk_score=parsed_risk.value,
        risk_score_status=parsed_risk.status,
        affected_work_order=_first_nonempty(row, ["work_order", "linked_work_order"]),
        affected_product=_first_nonempty(row, ["product_code", "product_code_stock", "product_code_po"]),
        affected_customer=_first_nonempty(row, ["customer_code", "customer_code_stock"]),
        affected_equipment=_first_nonempty(row, ["equipment_serial", "equipment_serial_stock"]),
        source_files=[source_file],
        source_record=_string_keyed_record(row),
        match_candidates=_match_candidates(
            input_dir,
            row,
            financial_input_policy=financial_input_policy,
            csv_cache=csv_cache,
        ),
        triggered_rules=_rule_results(
            input_dir,
            row,
            financial_input_policy=financial_input_policy,
            csv_cache=csv_cache,
        ),
        business_impact=business_impact(exception_type),
        recommended_action=recommended_action(exception_type),
        responsible_department=responsible_department(exception_type),
    )


def collect_evidence_cases(
    input_dir: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    _csv_cache: _GeneratedCsvCache | None = None,
) -> list[EvidenceCase]:
    """Collect High/Critical exception cases from a generated output folder."""

    input_policy = validate_financial_input_policy(financial_input_policy)
    base = Path(input_dir)
    csv_cache = _csv_cache if _csv_cache is not None else {}
    frames = [
        _risk_filter(
            _read_csv_if_exists(
                path,
                financial_input_policy=input_policy,
                cache=csv_cache,
            ),
            financial_input_policy=input_policy,
        )
        for path in _candidate_files(base)
    ]
    non_empty_frames = [frame for frame in frames if not frame.empty]
    if not non_empty_frames:
        return []
    combined = pd.concat(non_empty_frames, ignore_index=True, sort=False)
    if combined.empty:
        return []
    cases: list[EvidenceCase] = []
    for index, (_, row) in enumerate(combined.iterrows(), start=1):
        cases.append(
            _case_from_row(
                base,
                row,
                index,
                financial_input_policy=input_policy,
                csv_cache=csv_cache,
            )
        )
    return cases


def _apply_review_state(cases: list[EvidenceCase], input_dir: Path) -> list[EvidenceCase]:
    state = load_review_state(input_dir / "review_state.json")
    if not state:
        return cases
    updated_cases: list[EvidenceCase] = []
    for case in cases:
        entry = state.get(case.exception_id)
        if entry is None:
            updated_cases.append(case)
            continue
        updated_cases.append(
            case.model_copy(
                update={
                    "review_status": entry.get("status", "New"),
                    "reviewer": entry.get("reviewer", ""),
                    "review_note": entry.get("note", ""),
                    "review_updated_at": entry.get("updated_at", ""),
                    "decision_reason": entry.get("decision_reason", ""),
                    "accepted_risk_reason": entry.get("accepted_risk_reason", ""),
                    "escalation_owner": entry.get("escalation_owner", ""),
                    "prepared_by": entry.get("prepared_by", ""),
                    "prepared_at": entry.get("prepared_at", ""),
                    "reviewed_by": entry.get("reviewed_by", ""),
                    "reviewed_at": entry.get("reviewed_at", ""),
                    "certification_status": entry.get("certification_status", ""),
                    "certification_note": entry.get("certification_note", ""),
                },
            ),
        )
    return updated_cases


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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


def _selected_input_files(input_dir: Path) -> list[Path]:
    candidates = [
        *_candidate_files(input_dir),
        input_dir / "stock_gl_matched_transactions.csv",
        input_dir / "management_pack_stock_gl_matched_transactions.csv",
        input_dir / "rules" / "rule_results.csv",
        input_dir / "rule_results.csv",
        input_dir / "review_state.json",
    ]
    selected = {path.relative_to(input_dir).as_posix(): path for path in candidates if path.exists() and path.is_file()}
    return [selected[name] for name in sorted(selected)]


def _file_fingerprints(
    root: Path,
    paths: list[Path],
    *,
    csv_cache: _GeneratedCsvCache | None = None,
    verify_cached_csv: bool = False,
) -> list[dict[str, Any]]:
    fingerprints: list[dict[str, Any]] = []
    for path in paths:
        document = csv_cache.get(path) if csv_cache is not None else None
        if document is not None:
            if verify_cached_csv:
                verify_generated_csv_document(document)
            size_bytes = document.size_bytes
            checksum = document.checksum_sha256
        else:
            size_bytes = path.stat().st_size
            checksum = _sha256(path)
        fingerprints.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": size_bytes,
                "sha256": checksum,
            },
        )
    return fingerprints


def _content_cases(cases: object) -> object:
    if not isinstance(cases, list):
        return cases
    result: list[object] = []
    for case in cases:
        if isinstance(case, dict):
            result.append({key: value for key, value in case.items() if key != "generated_at"})
        else:
            result.append(case)
    return result


def _current_content_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_INDEX_SCHEMA_VERSION,
        "artifact_type": _EVIDENCE_INDEX_ARTIFACT_TYPE,
        "tool_version": payload.get("tool_version"),
        "financial_input_policy": payload.get("financial_input_policy"),
        "risk_score_policy": payload.get("risk_score_policy"),
        "input_files": payload.get("input_files"),
        "integrity_boundary": payload.get("integrity_boundary"),
        "case_count": payload.get("case_count"),
        "cases": _content_cases(payload.get("cases")),
    }


def _current_index_payload(
    cases: list[EvidenceCase],
    *,
    input_files: list[dict[str, Any]],
    financial_input_policy: FinancialInputPolicy,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": EVIDENCE_INDEX_SCHEMA_VERSION,
        "artifact_type": _EVIDENCE_INDEX_ARTIFACT_TYPE,
        "generated_at": utc_now_text(),
        "tool_version": __version__,
        "financial_input_policy": financial_input_policy,
        "risk_score_policy": EVIDENCE_RISK_SCORE_POLICY,
        "input_files": input_files,
        "integrity_boundary": _EVIDENCE_INDEX_INTEGRITY_BOUNDARY,
        "case_count": len(cases),
        "cases": [case.model_dump(mode="json") for case in cases],
    }
    payload["content_digest"] = _canonical_digest(_current_content_payload(payload))
    payload["artifact_digest"] = _canonical_digest(payload)
    return payload


def write_evidence_integrity_manifest(output_dir: Path | str, input_dir: Path | str) -> Path:
    """Write a SHA-256 integrity manifest for generated evidence artifacts."""

    target = Path(output_dir)
    manifest_path = target / "evidence_manifest.json"
    files = []
    for path in sorted(target.rglob("*")):
        if not path.is_file() or path == manifest_path or path.name.startswith("."):
            continue
        files.append(
            {
                "path": path.relative_to(target).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            },
        )
    write_json(
        {
            "generated_at": utc_now_text(),
            "tool_version": __version__,
            "source_output_folder": str(input_dir),
            "evidence_output_folder": str(target),
            "privacy_note": "Evidence files may contain generated extracts from local ERP outputs. Review before sharing.",
            "integrity_model": "SHA-256 checksums only; this is not a legal digital signature.",
            "files": files,
        },
        target,
        "evidence_manifest",
    )
    return manifest_path


def generate_evidence_binder(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> list[EvidenceArtifact]:
    """Generate enterprise-style audit evidence folders."""

    input_policy = validate_financial_input_policy(financial_input_policy)
    input_path = Path(input_dir)
    selected_inputs = _selected_input_files(input_path)
    csv_cache: _GeneratedCsvCache = {}
    for path in selected_inputs:
        if path.suffix.lower() == ".csv":
            _read_csv_if_exists(
                path,
                financial_input_policy=input_policy,
                cache=csv_cache,
            )
    input_files = _file_fingerprints(
        input_path,
        selected_inputs,
        csv_cache=csv_cache,
    )
    cases = _apply_review_state(
        collect_evidence_cases(
            input_path,
            financial_input_policy=input_policy,
            _csv_cache=csv_cache,
        ),
        input_path,
    )
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    artifacts = [write_evidence_case(case, target) for case in cases]
    write_evidence_index_html(cases, target)
    write_evidence_register(cases, target)
    final_selected_inputs = _selected_input_files(input_path)
    if (
        final_selected_inputs != selected_inputs
        or _file_fingerprints(
            input_path,
            final_selected_inputs,
            csv_cache=csv_cache,
            verify_cached_csv=True,
        )
        != input_files
    ):
        raise ValueError("Evidence binder source files changed during generation")
    payload: dict[str, Any]
    if input_policy == LEGACY_FINANCIAL_INPUT_POLICY:
        payload = {
            "schema_version": 2,
            "risk_score_policy": EVIDENCE_RISK_SCORE_POLICY,
            "case_count": len(cases),
            "cases": [case.model_dump(mode="json") for case in cases],
        }
    else:
        payload = _current_index_payload(
            cases,
            input_files=input_files,
            financial_input_policy=input_policy,
        )
    write_json(payload, target, "evidence_index")
    write_evidence_integrity_manifest(target, input_path)
    return artifacts


def _require_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Evidence index {field_name} must be an object")
    return value


def _safe_input_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Evidence index contains an unsafe input path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("Evidence index contains an unsafe input path")
    return value


def _validate_input_files(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Evidence index input_files must be an array of objects")
    records = list(value)
    paths: list[str] = []
    for item in records:
        path = _safe_input_path(item.get("path"))
        size_bytes = item.get("size_bytes")
        digest = item.get("sha256")
        if (
            set(item) != {"path", "size_bytes", "sha256"}
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or not isinstance(digest, str)
            or _SHA256_PATTERN.fullmatch(digest) is None
        ):
            raise ValueError("Evidence index contains an invalid input fingerprint")
        paths.append(path)
    if paths != sorted(set(paths)):
        raise ValueError("Evidence index input fingerprints must be unique and sorted")
    return records


def verify_evidence_index_payload(
    payload: dict[str, Any],
    *,
    source_dir: Path | str | None = None,
) -> None:
    """Verify a current evidence-index payload and optionally its local inputs."""

    expected_keys = {
        "schema_version",
        "artifact_type",
        "generated_at",
        "tool_version",
        "financial_input_policy",
        "risk_score_policy",
        "input_files",
        "integrity_boundary",
        "case_count",
        "cases",
        "content_digest",
        "artifact_digest",
    }
    if set(payload) != expected_keys:
        raise ValueError("Evidence index v3 fields are invalid")
    if payload.get("schema_version") != EVIDENCE_INDEX_SCHEMA_VERSION:
        raise ValueError("Only current v3 evidence indexes are verifiable")
    if payload.get("artifact_type") != _EVIDENCE_INDEX_ARTIFACT_TYPE:
        raise ValueError("Evidence index artifact type is invalid")
    input_policy = validate_financial_input_policy(payload.get("financial_input_policy"))
    if input_policy != STRICT_FINANCIAL_INPUT_POLICY:
        raise ValueError("Evidence index v3 requires the strict financial input policy")
    if payload.get("risk_score_policy") != EVIDENCE_RISK_SCORE_POLICY:
        raise ValueError("Evidence index risk-score policy is invalid")
    if payload.get("integrity_boundary") != _EVIDENCE_INDEX_INTEGRITY_BOUNDARY:
        raise ValueError("Evidence index integrity boundary is invalid")
    input_files = _validate_input_files(payload.get("input_files"))
    cases = payload.get("cases")
    case_count = payload.get("case_count")
    if (
        not isinstance(cases, list)
        or isinstance(case_count, bool)
        or not isinstance(case_count, int)
        or case_count < 0
        or case_count != len(cases)
    ):
        raise ValueError("Evidence index case count is invalid")
    try:
        for case in cases:
            EvidenceCase.model_validate(case)
    except (TypeError, ValueError) as exc:
        raise ValueError("Evidence index contains an invalid case") from exc
    content_digest = payload.get("content_digest")
    if not isinstance(content_digest, str) or not hmac.compare_digest(
        content_digest,
        _canonical_digest(_current_content_payload(payload)),
    ):
        raise ValueError("Evidence index content digest verification failed")
    artifact_digest = payload.get("artifact_digest")
    payload_without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    if not isinstance(artifact_digest, str) or not hmac.compare_digest(
        artifact_digest,
        _canonical_digest(payload_without_digest),
    ):
        raise ValueError("Evidence index artifact digest verification failed")
    if source_dir is not None:
        source_root = Path(source_dir)
        current_inputs = _file_fingerprints(
            source_root,
            _selected_input_files(source_root),
        )
        if input_files != current_inputs:
            raise ValueError("Evidence index input fingerprint verification failed")


def read_evidence_index(path: Path | str) -> EvidenceIndexDocument:
    """Read legacy schema-v2 or verify current schema-v3 evidence indexes."""

    source = Path(path)
    try:
        payload = read_json_document(source)
    except StructuredDocumentError as exc:
        raise ValueError("Evidence index JSON is invalid") from exc
    document = _require_mapping(payload, "document")
    if document.get("schema_version") == 2:
        if (
            set(document) != {"schema_version", "risk_score_policy", "case_count", "cases"}
            or document.get("risk_score_policy") != EVIDENCE_RISK_SCORE_POLICY
            or isinstance(document.get("case_count"), bool)
            or not isinstance(document.get("case_count"), int)
            or not isinstance(document.get("cases"), list)
            or document.get("case_count") != len(document.get("cases", []))
        ):
            raise ValueError("Legacy evidence index fields are invalid")
        return EvidenceIndexDocument(
            schema_version=2,
            verification_status="legacy-unverified",
            payload=document,
        )
    verify_evidence_index_payload(document)
    return EvidenceIndexDocument(
        schema_version=3,
        verification_status="verified",
        payload=document,
    )
