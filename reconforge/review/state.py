"""Local JSON review state for exception workflows."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypeAlias, cast

import pandas as pd

from reconforge.io.excel import write_excel_workbook
from reconforge.io.generated import (
    GeneratedCsvMode,
    read_generated_csv_document,
    read_generated_json_document,
)
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
    validate_financial_input_policy,
)
from reconforge.utils.time import utc_now_text

ReviewStatus = Literal["New", "Under Review", "Resolved", "Accepted Risk", "Escalated"]
ALLOWED_STATUSES: tuple[ReviewStatus, ...] = ("New", "Under Review", "Resolved", "Accepted Risk", "Escalated")
DEFAULT_STATUS: ReviewStatus = "New"
CertificationStatus = Literal["Draft", "Prepared", "Reviewed", "Accepted Risk", "Needs Follow-up"]
ALLOWED_CERTIFICATION_STATUSES: tuple[CertificationStatus, ...] = (
    "Draft",
    "Prepared",
    "Reviewed",
    "Accepted Risk",
    "Needs Follow-up",
)


ReviewEntry: TypeAlias = dict[str, str]
ReviewState: TypeAlias = dict[str, ReviewEntry]

REVIEW_STATE_INGRESS_PROFILE = "review-state-json-ingress-v1"
REVIEW_STATE_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=16 * 1024 * 1024,
    max_nodes=500_000,
    max_depth=32,
    max_collection_items=100_000,
    max_scalar_characters=1_000_000,
    max_yaml_aliases=1,
)

EXCEPTION_FILE_CANDIDATES = [
    "management_pack_stock_gl_all_exceptions.csv",
    "management_pack_workorders_all_exceptions.csv",
    "stock_gl_all_exceptions.csv",
    "workorders_all_exceptions.csv",
]

REVIEW_COLUMNS = [
    "exception_id",
    "status",
    "reviewer",
    "note",
    "updated_at",
    "decision_reason",
    "accepted_risk_reason",
    "escalation_owner",
    "prepared_by",
    "prepared_at",
    "reviewed_by",
    "reviewed_at",
    "certification_status",
    "certification_note",
]

CERTIFICATION_COLUMNS = [
    "prepared_by",
    "prepared_at",
    "reviewed_by",
    "reviewed_at",
    "certification_status",
    "certification_note",
]


def _now() -> str:
    return utc_now_text()


def _clean_text(value: object) -> str:
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "null"} else text


def _coerce_status(value: object) -> ReviewStatus:
    text = _clean_text(value)
    for status in ALLOWED_STATUSES:
        if text.lower() == status.lower():
            return status
    raise ValueError(f"Invalid review status '{value}'. Expected one of: {', '.join(ALLOWED_STATUSES)}")


def _coerce_certification_status(value: object) -> CertificationStatus:
    text = _clean_text(value)
    if not text:
        return "Draft"
    normalized = text.lower().replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())
    for status in ALLOWED_CERTIFICATION_STATUSES:
        if normalized == status.lower():
            return status
    raise ValueError(f"Invalid certification status. Expected one of: {', '.join(ALLOWED_CERTIFICATION_STATUSES)}")


def _coerce_entry(exception_id: str, payload: object) -> ReviewEntry | None:
    if not isinstance(payload, dict):
        return None
    try:
        status = _coerce_status(payload.get("status", DEFAULT_STATUS))
    except ValueError:
        status = DEFAULT_STATUS
    entry: ReviewEntry = {"exception_id": exception_id, "status": status}
    for field in [
        "reviewer",
        "note",
        "updated_at",
        "decision_reason",
        "accepted_risk_reason",
        "escalation_owner",
        "prepared_by",
        "prepared_at",
        "reviewed_by",
        "reviewed_at",
        "certification_note",
    ]:
        value = payload.get(field)
        if value is not None:
            entry[field] = _clean_text(value)
    certification_status = payload.get("certification_status")
    if certification_status is not None:
        try:
            entry["certification_status"] = _coerce_certification_status(certification_status)
        except ValueError:
            entry["certification_status"] = "Draft"
    return entry


def load_review_state(path: Path | str) -> ReviewState:
    """Load bounded local review state while retaining legacy entry coercion."""

    state_path = Path(path)
    if not state_path.exists():
        return {}
    payload = read_generated_json_document(
        state_path,
        policy=REVIEW_STATE_JSON_POLICY,
        profile_id=REVIEW_STATE_INGRESS_PROFILE,
    ).payload
    raw_entries: object
    if isinstance(payload, dict) and isinstance(payload.get("entries"), dict):
        raw_entries = payload["entries"]
    elif isinstance(payload, dict):
        raw_entries = payload
    else:
        return {}
    entries: ReviewState = {}
    for key, value in cast(dict[str, object], raw_entries).items():
        exception_id = _clean_text(key)
        if not exception_id:
            continue
        entry = _coerce_entry(exception_id, value)
        if entry is not None:
            entries[exception_id] = entry
    return entries


def save_review_state(path: Path | str, state: ReviewState) -> Path:
    """Save review state as local JSON without removing unknown entries."""

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "entries": state}
    temp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(state_path)
    return state_path


def get_review_status(exception_id: str, state: ReviewState) -> ReviewStatus:
    """Return the saved review status for an exception, defaulting to New."""

    entry = state.get(exception_id, {})
    return _coerce_status(entry.get("status", DEFAULT_STATUS))


def update_review_status(
    exception_id: str,
    status: str,
    state: ReviewState,
    *,
    reviewer: str = "",
    note: str = "",
    decision_reason: str = "",
    accepted_risk_reason: str = "",
    escalation_owner: str = "",
    prepared_by: str = "",
    prepared_at: str = "",
    reviewed_by: str = "",
    reviewed_at: str = "",
    certification_status: str = "",
    certification_note: str = "",
) -> ReviewEntry:
    """Update one exception review entry in memory and return the updated entry."""

    clean_exception_id = _clean_text(exception_id)
    if not clean_exception_id:
        raise ValueError("exception_id is required")
    entry: ReviewEntry = dict(state.get(clean_exception_id, {"exception_id": clean_exception_id}))
    entry["exception_id"] = clean_exception_id
    entry["status"] = _coerce_status(status)
    updates = {
        "reviewer": reviewer,
        "note": note,
        "decision_reason": decision_reason,
        "accepted_risk_reason": accepted_risk_reason,
        "escalation_owner": escalation_owner,
        "prepared_by": prepared_by,
        "prepared_at": prepared_at,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "certification_note": certification_note,
    }
    for field, value in updates.items():
        clean_value = _clean_text(value)
        if clean_value:
            entry[field] = clean_value
    if _clean_text(prepared_by) and not _clean_text(prepared_at):
        entry["prepared_at"] = _now()
    if _clean_text(reviewed_by) and not _clean_text(reviewed_at):
        entry["reviewed_at"] = _now()
    if _clean_text(certification_status):
        entry["certification_status"] = _coerce_certification_status(certification_status)
    entry["updated_at"] = _now()
    state[clean_exception_id] = entry
    return entry


def _amount_impact(
    row: pd.Series,
    *,
    financial_input_policy: FinancialInputPolicy,
) -> Decimal | None:
    for field in ("amount_impact", "amount", "total_cost", "actual_cost", "estimated_cost", "invoice_amount", "total_price"):
        value = row.get(field)
        try:
            return abs(
                parse_amount(
                    value,
                    input_policy=financial_input_policy,
                )
            )
        except InvalidAmountError:
            continue
    return None


def _source_file(frame_path: Path, frame: pd.DataFrame) -> pd.Series:
    if "source_file" in frame.columns:
        return frame["source_file"].astype(str)
    return pd.Series([frame_path.name] * len(frame), index=frame.index)


def collect_exception_frame(
    input_dir: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> pd.DataFrame:
    """Collect generated exception CSV files into one deterministic frame."""

    input_policy = validate_financial_input_policy(financial_input_policy)
    base = Path(input_dir)
    frames: list[pd.DataFrame] = []
    for filename in EXCEPTION_FILE_CANDIDATES:
        path = base / filename
        if not path.exists():
            continue
        mode: GeneratedCsvMode = (
            "exact-text"
            if input_policy == STRICT_FINANCIAL_INPUT_POLICY
            else "display"
        )
        frame = read_generated_csv_document(path, mode=mode).frame
        if frame.empty:
            continue
        frame = frame.copy()
        frame["source_file"] = _source_file(path, frame)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=[
                "exception_id",
                "status",
                "reviewer",
                "note",
                "updated_at",
                "severity",
                "exception_type",
                "amount_impact",
                "source_file",
            ],
        )
    combined = pd.concat(frames, ignore_index=True, sort=False)
    return _ensure_exception_columns(
        combined,
        financial_input_policy=input_policy,
    )


def _ensure_exception_columns(
    frame: pd.DataFrame,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> pd.DataFrame:
    output = frame.copy()
    if "exception_id" not in output.columns:
        output.insert(0, "exception_id", [f"EXC-{index:04d}" for index in range(1, len(output) + 1)])
    else:
        missing = output["exception_id"].astype(str).str.strip().eq("")
        if missing.any():
            output.loc[missing, "exception_id"] = [f"EXC-{index:04d}" for index in range(1, int(missing.sum()) + 1)]
    if "severity" not in output.columns:
        if "risk_level" in output.columns:
            output["severity"] = output["risk_level"]
        else:
            output["severity"] = ""
    if "exception_type" not in output.columns:
        if "rule_name" in output.columns:
            output["exception_type"] = output["rule_name"]
        else:
            output["exception_type"] = "unclassified_exception"
    if "amount_impact" not in output.columns:
        output["amount_impact"] = [
            _amount_impact(
                row,
                financial_input_policy=financial_input_policy,
            )
            for _, row in output.iterrows()
        ]
    if "source_file" not in output.columns:
        output["source_file"] = ""
    return output


def merge_review_state_with_exceptions(exceptions: pd.DataFrame, state: ReviewState) -> pd.DataFrame:
    """Add local review-state fields to an exception frame."""

    merged = _ensure_exception_columns(exceptions)
    for column in REVIEW_COLUMNS[1:]:
        if column not in merged.columns:
            merged[column] = ""
    for index, row in merged.iterrows():
        exception_id = _clean_text(row.get("exception_id", ""))
        entry = state.get(exception_id, {})
        merged.at[index, "status"] = entry.get("status", DEFAULT_STATUS)
        for field in REVIEW_COLUMNS[2:]:
            merged.at[index, field] = entry.get(field, "")
    return merged


def review_register_frame(
    input_dir: Path | str,
    state_path: Path | str | None = None,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> pd.DataFrame:
    """Build a review register frame from generated exceptions and local state."""

    base = Path(input_dir)
    review_state_path = Path(state_path) if state_path is not None else base / "review_state.json"
    merged = merge_review_state_with_exceptions(
        collect_exception_frame(
            base,
            financial_input_policy=financial_input_policy,
        ),
        load_review_state(review_state_path),
    )
    columns = [
        "exception_id",
        "status",
        "reviewer",
        "note",
        "updated_at",
        "prepared_by",
        "prepared_at",
        "reviewed_by",
        "reviewed_at",
        "certification_status",
        "certification_note",
        "severity",
        "exception_type",
        "amount_impact",
        "source_file",
        "decision_reason",
        "accepted_risk_reason",
        "escalation_owner",
    ]
    for column in columns:
        if column not in merged.columns:
            merged[column] = ""
    return merged[columns].copy()


def export_review_register(
    input_dir: Path | str,
    output_path: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> Path:
    """Export local review state merged with exceptions to an Excel workbook."""

    input_policy = validate_financial_input_policy(financial_input_policy)
    register = review_register_frame(
        input_dir,
        financial_input_policy=input_policy,
    )
    parameters = pd.DataFrame(
        [{"financial_input_policy": input_policy}],
    )
    return write_excel_workbook(
        {
            "Review Register": register,
            "Report Parameters": parameters,
        },
        output_path,
    )
