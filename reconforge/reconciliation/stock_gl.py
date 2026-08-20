"""Stock movement to GL reconciliation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.matching import (
    DUPLICATE_COUNT_COLUMN,
    DUPLICATE_ORDINAL_COLUMN,
    RECORD_FINGERPRINT_COLUMN,
    RECORD_IDENTITY_POLICY,
    RECORD_IDENTITY_POLICY_COLUMN,
    RECORD_INSTANCE_ID_COLUMN,
    SOURCE_POSITION_COLUMN,
    SOURCE_ROW_BASIS,
    SOURCE_ROW_BASIS_COLUMN,
    SOURCE_ROW_COLUMN,
    MatchAmbiguity,
    MatchCandidate,
    MatchingAmbiguityPolicy,
    MatchingStrategy,
    assign_stock_to_gl,
    normalize_reference,
    prepare_record_lineage,
)
from reconforge.reconciliation.risk import assess_risk
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    CurrencyRegistry,
    FinancialInputPolicy,
    InvalidAmountError,
    Money,
    UnknownCurrencyError,
    parse_amount,
    parse_amount_for_currency_precision,
    validate_financial_input_policy,
)


@dataclass(frozen=True)
class StockGLReconciliationResult:
    """Output frames from stock-vs-GL reconciliation."""

    matched_transactions: pd.DataFrame
    stock_without_gl: pd.DataFrame
    gl_without_stock: pd.DataFrame
    value_differences: pd.DataFrame
    date_differences: pd.DataFrame
    reference_mismatches: pd.DataFrame
    data_quality_exceptions: pd.DataFrame
    all_exceptions: pd.DataFrame
    summary: pd.DataFrame
    invariants: dict[str, int | bool] = field(default_factory=dict)
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY
    record_identity_policy: str = RECORD_IDENTITY_POLICY
    matching_ambiguity_policy: str = "stable-tie-break-v1"

    def __post_init__(self) -> None:
        """Reject unsupported policy metadata before a result can escape."""

        object.__setattr__(
            self,
            "financial_input_policy",
            validate_financial_input_policy(self.financial_input_policy),
        )


_EXCEPTION_REASONS = {
    "stock_without_gl": "No eligible GL entry was assigned to the stock movement.",
    "gl_without_stock": "No eligible stock movement was assigned to the GL entry.",
    "value_difference": "Matched source and GL amounts differ beyond the configured tolerance.",
    "date_difference": "Matched source and GL postings have different dates.",
    "reference_mismatch": "Normalized source and GL references do not agree.",
    "data_quality": "A required financial amount is missing, malformed, or non-finite.",
    "ambiguous_match": "Multiple equal-cost assignments exist or the bounded ambiguity search budget was exceeded.",
}

_EXCEPTION_METADATA: dict[str, dict[str, str]] = {
    "stock_without_gl": {
        "title": "Stock movement without GL posting",
        "explanation": "No GL posting was assigned to this stock movement.",
        "suggested_action": "Verify whether the stock movement posted to a different GL period or account.",
        "severity": "High",
        "ownership": "Reconciliation analyst",
        "workflow_status": "Open",
    },
    "gl_without_stock": {
        "title": "GL posting without stock movement",
        "explanation": "No stock movement matched this GL posting.",
        "suggested_action": "Review posting source and mapping rules for missing stock activity.",
        "severity": "High",
        "ownership": "Accounting reviewer",
        "workflow_status": "Open",
    },
    "value_difference": {
        "title": "Material value difference",
        "explanation": "Matched records are materially different after tolerance checks.",
        "suggested_action": "Investigate cost/amount posting rules and verify source documents.",
        "severity": "High",
        "ownership": "Reconciliation analyst",
        "workflow_status": "In Review",
    },
    "date_difference": {
        "title": "Posting date mismatch",
        "explanation": "Matched stock and GL records have an unexpected date gap.",
        "suggested_action": "Review cutoff periods and late posting reasons.",
        "severity": "Medium",
        "ownership": "Controller",
        "workflow_status": "In Review",
    },
    "reference_mismatch": {
        "title": "Reference mismatch",
        "explanation": "Normalized references do not reconcile to the same transaction family.",
        "suggested_action": "Confirm normalization rules and update mapping when vendor references are inconsistent.",
        "severity": "Medium",
        "ownership": "Reconciliation analyst",
        "workflow_status": "In Review",
    },
    "data_quality": {
        "title": "Invalid financial amount",
        "explanation": "The required amount could not be parsed as a valid finite decimal.",
        "suggested_action": "Correct source data and rerun validation before matching.",
        "severity": "Critical",
        "ownership": "Data steward",
        "workflow_status": "Open",
    },
    "ambiguous_match": {
        "title": "Unresolved matching ambiguity",
        "explanation": "The configured conservative policy found no unique bounded optimum.",
        "suggested_action": "Review the candidate group and add a discriminating rule or source identifier.",
        "severity": "High",
        "ownership": "Reconciliation reviewer",
        "workflow_status": "Open",
    },
}

_TRANSIENT_EXCEPTION_COLUMNS = {
    "risk_score",
    "risk_level",
    "exception_id",
    "exception_type",
    "exception_reason",
    "exception_title",
    "exception_explanation",
    "suggested_action",
    "severity",
    "source_row",
    "source_position",
    "source_row_basis",
    "ownership",
    "workflow_status",
    "evidence_reference",
    "match_reason",
    "review_required",
}


def _record_lineage_fields(row: pd.Series, *, prefix: str = "") -> dict[str, object]:
    return {
        f"{prefix}record_instance_id": row.get(RECORD_INSTANCE_ID_COLUMN),
        f"{prefix}record_fingerprint": row.get(RECORD_FINGERPRINT_COLUMN),
        f"{prefix}duplicate_ordinal": int(row.get(DUPLICATE_ORDINAL_COLUMN) or 1),
        f"{prefix}duplicate_count": int(row.get(DUPLICATE_COUNT_COLUMN) or 1),
        f"{prefix}source_position": int(row.get(SOURCE_POSITION_COLUMN) or 0),
        f"{prefix}source_row": int(row.get(SOURCE_ROW_COLUMN) or 0),
        f"{prefix}source_row_basis": str(row.get(SOURCE_ROW_BASIS_COLUMN) or SOURCE_ROW_BASIS),
        f"{prefix}record_identity_policy": str(row.get(RECORD_IDENTITY_POLICY_COLUMN) or RECORD_IDENTITY_POLICY),
    }


def _expose_record_lineage(frame: pd.DataFrame) -> pd.DataFrame:
    exposed = frame.copy()
    renames = {
        RECORD_INSTANCE_ID_COLUMN: "record_instance_id",
        RECORD_FINGERPRINT_COLUMN: "record_fingerprint",
        DUPLICATE_ORDINAL_COLUMN: "duplicate_ordinal",
        DUPLICATE_COUNT_COLUMN: "duplicate_count",
        SOURCE_POSITION_COLUMN: "source_position",
        SOURCE_ROW_COLUMN: "source_row",
        SOURCE_ROW_BASIS_COLUMN: "source_row_basis",
        RECORD_IDENTITY_POLICY_COLUMN: "record_identity_policy",
    }
    return exposed.rename(columns=renames)


def _stable_output_order(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    """Return a result frame in a deterministic order independent of input rows.

    Source positions remain attached as audit metadata, but they are not an
    ordering key: reordering an input file must not reorder the canonical
    result artifact.  Stringifying only the selected identity columns also
    avoids pandas attempting to compare heterogeneous financial values.
    """

    if frame.empty:
        return frame.reset_index(drop=True)
    available = [column for column in columns if column in frame.columns]
    if not available:
        return frame.reset_index(drop=True)
    ordered = frame.copy()
    ordered["_reconforge_output_sort_key"] = (
        ordered[available].astype("string").fillna("").agg("\x1f".join, axis=1)
    )
    return (
        ordered.sort_values("_reconforge_output_sort_key", kind="mergesort")
        .drop(columns=["_reconforge_output_sort_key"])
        .reset_index(drop=True)
    )


def _canonical_exception_value(
    value: object,
    *,
    input_policy: FinancialInputPolicy,
) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (int, float, Decimal, str)):
        try:
            parsed = parse_amount(
                value,
                input_policy=input_policy,
                _warn_on_legacy_input=False,
            )
            normalized = format(parsed.normalize(), "f")
            return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized
        except InvalidAmountError:
            return str(value).strip()
    return str(value).strip()


def _exception_payload(
    row: pd.Series,
    *,
    input_policy: FinancialInputPolicy,
) -> str:
    payload = {}
    for key in sorted(
        str(column)
        for column in row.index
        if str(column) not in _TRANSIENT_EXCEPTION_COLUMNS
        and not str(column).endswith(("source_position", "source_row", "source_row_basis"))
    ):
        payload[key] = _canonical_exception_value(
            row.get(key),
            input_policy=input_policy,
        )
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _safe_amount(
    value: object,
    *,
    input_policy: FinancialInputPolicy,
) -> Decimal | None:
    try:
        return parse_amount(
            value,
            input_policy=input_policy,
            _warn_on_legacy_input=False,
        )
    except InvalidAmountError:
        return None


def _parse_date(value: object) -> date | None:
    """Parse one reconciliation date without treating invalid data as a date."""

    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(str(value).strip(), errors="coerce")
    if not isinstance(parsed, pd.Timestamp) or pd.isna(parsed):
        return None
    return parsed.date()


def _missing_or_invalid(value: object) -> str:
    if value is None:
        return "missing"
    try:
        if bool(pd.isna(value)):
            return "missing"
    except (TypeError, ValueError):
        return "invalid"
    return "missing" if not str(value).strip() else "invalid"


def _exception_id(
    exception_type: str,
    row: pd.Series,
    *,
    input_policy: FinancialInputPolicy,
) -> str:
    identity = f"{exception_type}|{_exception_payload(row, input_policy=input_policy)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20].upper()
    return f"EXC-{digest}"


def _risk_columns(
    frame: pd.DataFrame,
    exception_type: str,
    config: ReconForgeConfig,
    amount_column: str,
    difference_column: str | None = None,
    *,
    input_policy: FinancialInputPolicy,
) -> pd.DataFrame:
    enriched = frame.copy()
    scores: list[int] = []
    levels: list[str] = []
    metadata = _EXCEPTION_METADATA.get(
        exception_type,
        {
            "title": exception_type.replace("_", " ").title(),
            "explanation": _EXCEPTION_REASONS.get(exception_type, "Reconciliation exception"),
            "suggested_action": "Review in workflow and document a decision.",
            "severity": "Medium",
            "ownership": "Reconciliation analyst",
            "workflow_status": "Open",
        },
    )
    for _, row in enriched.iterrows():
        amount_value = _safe_amount(row.get(amount_column), input_policy=input_policy)
        difference_value = (
            _safe_amount(row.get(difference_column), input_policy=input_policy) if difference_column else None
        )
        assessment = assess_risk(
            exception_type,
            config,
            # A missing amount has no valid magnitude to score. The zero here is
            # only the risk model's neutral magnitude, never a persisted amount.
            amount=amount_value if amount_value is not None else Decimal("0"),
            amount_difference=abs(difference_value) if difference_value is not None else Decimal("0"),
        )
        scores.append(assessment.score)
        levels.append(assessment.level)
    enriched["exception_type"] = exception_type
    enriched["exception_reason"] = _EXCEPTION_REASONS[exception_type]
    enriched["exception_title"] = metadata["title"]
    enriched["exception_explanation"] = metadata["explanation"]
    enriched["suggested_action"] = metadata["suggested_action"]
    enriched["severity"] = metadata["severity"]
    enriched["risk_score"] = scores
    enriched["risk_level"] = levels
    enriched["ownership"] = metadata["ownership"]
    enriched["workflow_status"] = metadata["workflow_status"]
    enriched["exception_id"] = [
        _exception_id(
            exception_type,
            cast("pd.Series[Any]", row),
            input_policy=input_policy,
        )
        for _, row in enriched.iterrows()
    ]
    enriched["evidence_reference"] = enriched.apply(
        lambda row: str(
            row.get("match_id")
            or row.get("move_id")
            or row.get("entry_id")
            or _exception_payload(
                cast("pd.Series[Any]", row),
                input_policy=input_policy,
            ),
        ),
        axis=1,
    )
    return enriched


def _data_quality_exceptions(
    stock: pd.DataFrame,
    gl: pd.DataFrame,
    config: ReconForgeConfig,
    *,
    input_policy: FinancialInputPolicy,
) -> tuple[pd.DataFrame, set[int], set[int]]:
    rows: list[dict[str, object]] = []
    invalid_stock: set[int] = set()
    invalid_gl: set[int] = set()
    for dataset, frame, data_field, identifier, invalid_indices in (
        ("stock_moves", stock, "total_cost", "move_id", invalid_stock),
        ("stock_moves", stock, "date", "move_id", invalid_stock),
        ("gl_entries", gl, "amount", "entry_id", invalid_gl),
        ("gl_entries", gl, "date", "entry_id", invalid_gl),
    ):
        raw_column = f"_reconforge_raw_{data_field}"
        for raw_index, row in frame.iterrows():
            index = int(cast(int, raw_index))
            value = row.get(data_field)
            invalid_reason: str | None = None
            exception_field = data_field
            raw_value = row.get(raw_column, value)
            if data_field in {"total_cost", "amount"}:
                currency_code = str(row.get("currency") or "USD").strip().upper() or "USD"
                try:
                    precision = CurrencyRegistry.get_precision(currency_code)
                    parse_amount_for_currency_precision(
                        value,
                        precision=precision,
                        input_policy=input_policy,
                    )
                except UnknownCurrencyError:
                    invalid_reason = "unknown_currency"
                    exception_field = "currency"
                    raw_value = row.get("currency")
                except InvalidAmountError:
                    invalid_reason = "invalid_amount"
            elif _parse_date(value) is None:
                invalid_reason = f"{_missing_or_invalid(value)}_date"
            if invalid_reason is not None:
                invalid_indices.add(index)
                rows.append(
                    {
                        "source_dataset": dataset,
                        **_record_lineage_fields(cast("pd.Series[Any]", row)),
                        "field": exception_field,
                        "invalid_value": "" if raw_value is None or pd.isna(raw_value) else str(raw_value),
                        "parse_error": invalid_reason,
                        identifier: row.get(identifier),
                        "amount_impact": None,
                    },
                )
    quality = pd.DataFrame(rows)
    if quality.empty:
        quality = pd.DataFrame(
            columns=[
                "source_dataset",
                "source_row",
                "source_position",
                "source_row_basis",
                "record_instance_id",
                "record_fingerprint",
                "duplicate_ordinal",
                "duplicate_count",
                "record_identity_policy",
                "field",
                "invalid_value",
                "parse_error",
                "move_id",
                "entry_id",
                "amount_impact",
            ],
        )
    return (
        _risk_columns(
            quality,
            "data_quality",
            config,
            "amount_impact",
            input_policy=input_policy,
        ),
        invalid_stock,
        invalid_gl,
    )


def _build_match_rows(
    stock_moves: pd.DataFrame,
    gl_entries: pd.DataFrame,
    matches: list[MatchCandidate],
    config: ReconForgeConfig,
    *,
    input_policy: FinancialInputPolicy,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for match in matches:
        stock = cast("pd.Series[Any]", stock_moves.loc[match.stock_index])
        gl = cast("pd.Series[Any]", gl_entries.loc[match.gl_index])
        stock_currency = str(stock.get("currency") or "USD").strip().upper() or "USD"
        gl_currency = str(gl.get("currency") or "USD").strip().upper() or "USD"
        stock_money = Money(
            stock.get("total_cost"),
            stock_currency,
            strict_precision=True,
            input_policy=input_policy,
        )
        gl_money = Money(
            gl.get("amount"),
            gl_currency,
            strict_precision=True,
            input_policy=input_policy,
        )
        stock_amount = stock_money.amount
        gl_amount = gl_money.amount
        value_difference = (stock_money - gl_money).amount
        date_difference = match.date_difference
        assessment = assess_risk(
            "value_difference" if match.match_level == "Value Difference" else "matched",
            config,
            amount=stock_amount,
            amount_difference=abs(value_difference),
        )
        rows.append(
            {
                "move_id": stock.get("move_id"),
                "entry_id": gl.get("entry_id"),
                "match_id": match.match_id,
                "stock_record_instance_id": match.stock_record_instance_id,
                "gl_record_instance_id": match.gl_record_instance_id,
                "stock_duplicate_ordinal": match.stock_duplicate_ordinal,
                "gl_duplicate_ordinal": match.gl_duplicate_ordinal,
                "stock_duplicate_count": match.stock_duplicate_count,
                "gl_duplicate_count": match.gl_duplicate_count,
                "stock_source_position": match.stock_source_position,
                "gl_source_position": match.gl_source_position,
                "stock_source_row": match.stock_source_row,
                "gl_source_row": match.gl_source_row,
                "source_row_basis": SOURCE_ROW_BASIS,
                "record_identity_policy": RECORD_IDENTITY_POLICY,
                "stock_date": stock.get("date"),
                "gl_date": gl.get("date"),
                "source_document": stock.get("source_document"),
                "gl_reference": gl.get("reference"),
                "source_document_normalized": normalize_reference(stock.get("source_document")),
                "gl_reference_normalized": normalize_reference(gl.get("reference")),
                "work_order": stock.get("work_order"),
                "product_code": stock.get("product_code"),
                "product_name": stock.get("product_name"),
                "currency": stock_money.currency,
                "stock_amount": stock_amount,
                "gl_amount": gl_amount,
                "value_difference": value_difference,
                "date_difference_days": date_difference,
                "match_level": match.match_level,
                "confidence_score": match.confidence,
                "reference_similarity": match.reference_similarity,
                "match_reason": match.reason,
                "review_required": match.review_required,
                "risk_score": assessment.score if match.match_level == "Value Difference" else 0,
                "risk_level": assessment.level if match.match_level == "Value Difference" else "Low",
            },
        )
    return pd.DataFrame(rows)


def _summary_frame(result_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = [
        {"metric": "matched_transactions", "count": len(result_frames["matched_transactions"])},
        {"metric": "stock_without_gl", "count": len(result_frames["stock_without_gl"])},
        {"metric": "gl_without_stock", "count": len(result_frames["gl_without_stock"])},
        {"metric": "value_differences", "count": len(result_frames["value_differences"])},
        {"metric": "date_differences", "count": len(result_frames["date_differences"])},
        {"metric": "reference_mismatches", "count": len(result_frames["reference_mismatches"])},
    ]
    return pd.DataFrame(rows)


def _ambiguity_frame(
    frame: pd.DataFrame,
    ambiguities: tuple[MatchAmbiguity, ...],
    *,
    side: str,
    ambiguity_policy: MatchingAmbiguityPolicy,
) -> pd.DataFrame:
    """Return source rows participating in unresolved candidate components."""

    by_index: dict[int, MatchAmbiguity] = {}
    for ambiguity in ambiguities:
        indices = ambiguity.stock_indices if side == "stock" else ambiguity.gl_indices
        for index in indices:
            by_index[index] = ambiguity
    unresolved = frame[frame.index.isin(by_index)].copy()
    unresolved["ambiguity_group_id"] = [by_index[int(index)].ambiguity_group_id for index in unresolved.index]
    unresolved["ambiguity_reason"] = [by_index[int(index)].reason for index in unresolved.index]
    unresolved["ambiguity_candidate_count"] = [by_index[int(index)].candidate_count for index in unresolved.index]
    unresolved["ambiguity_optimal_cardinality"] = [
        by_index[int(index)].optimal_cardinality for index in unresolved.index
    ]
    unresolved["ambiguity_optimal_cost"] = [by_index[int(index)].optimal_cost for index in unresolved.index]
    unresolved["matching_ambiguity_policy"] = ambiguity_policy
    return unresolved


def reconcile_stock_gl(
    stock_moves: pd.DataFrame,
    gl_entries: pd.DataFrame,
    config: ReconForgeConfig,
    matching_strategy: MatchingStrategy = "standard",
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    ambiguity_policy: MatchingAmbiguityPolicy | None = None,
    _source_positions_trusted: bool = False,
) -> StockGLReconciliationResult:
    """Reconcile stock movements against GL postings."""

    input_policy = validate_financial_input_policy(input_policy)
    resolved_ambiguity_policy = ambiguity_policy or config.matching_ambiguity_policy
    stock = prepare_record_lineage(
        stock_moves.reset_index(drop=True),
        identifier="move_id",
        kind="stock",
        preserve_source_positions=_source_positions_trusted,
    )
    gl = prepare_record_lineage(
        gl_entries.reset_index(drop=True),
        identifier="entry_id",
        kind="gl",
        preserve_source_positions=_source_positions_trusted,
    )
    data_quality, invalid_stock_indices, invalid_gl_indices = _data_quality_exceptions(
        stock,
        gl,
        config,
        input_policy=input_policy,
    )
    matchable_stock = stock[~stock.index.isin(invalid_stock_indices)]
    matchable_gl = gl[~gl.index.isin(invalid_gl_indices)]
    assignment = assign_stock_to_gl(
        matchable_stock,
        matchable_gl,
        config,
        strategy=matching_strategy,
        input_policy=input_policy,
        lineage_prepared=True,
        ambiguity_policy=resolved_ambiguity_policy,
    )
    matches = list(assignment.matches)
    matched_indices = {match.stock_index for match in matches}
    matched_gl_indices = {match.gl_index for match in matches}

    matched = _build_match_rows(
        stock,
        gl,
        matches,
        config,
        input_policy=input_policy,
    )
    if matched.empty:
        matched = pd.DataFrame(
            columns=[
                "move_id",
                "entry_id",
                "match_id",
                "stock_record_instance_id",
                "gl_record_instance_id",
                "stock_duplicate_ordinal",
                "gl_duplicate_ordinal",
                "stock_duplicate_count",
                "gl_duplicate_count",
                "stock_source_position",
                "gl_source_position",
                "stock_source_row",
                "gl_source_row",
                "source_row_basis",
                "record_identity_policy",
                "stock_date",
                "gl_date",
                "source_document",
                "gl_reference",
                "source_document_normalized",
                "gl_reference_normalized",
                "work_order",
                "product_code",
                "product_name",
                "currency",
                "stock_amount",
                "gl_amount",
                "value_difference",
                "date_difference_days",
                "match_level",
                "confidence_score",
                "reference_similarity",
                "match_reason",
                "review_required",
                "risk_score",
                "risk_level",
            ],
        )
    matched = _stable_output_order(matched, "match_id", "stock_record_instance_id", "gl_record_instance_id")

    value_differences = _risk_columns(
        matched[matched["match_level"].eq("Value Difference")].copy(),
        "value_difference",
        config,
        "stock_amount",
        "value_difference",
        input_policy=input_policy,
    )
    date_differences = _risk_columns(
        matched[matched["date_difference_days"].notna() & matched["date_difference_days"].gt(0)].copy(),
        "date_difference",
        config,
        "stock_amount",
        input_policy=input_policy,
    )
    reference_mismatches = _risk_columns(
        matched[
            matched["source_document_normalized"].astype(str).ne(matched["gl_reference_normalized"].astype(str))
        ].copy(),
        "reference_mismatch",
        config,
        "stock_amount",
        "value_difference",
        input_policy=input_policy,
    )

    ambiguous_stock_indices = {index for ambiguity in assignment.ambiguities for index in ambiguity.stock_indices}
    ambiguous_gl_indices = {index for ambiguity in assignment.ambiguities for index in ambiguity.gl_indices}
    regular_stock_without = _expose_record_lineage(
        stock[~stock.index.isin(matched_indices | invalid_stock_indices | ambiguous_stock_indices)].copy()
    )
    regular_gl_without = _expose_record_lineage(
        gl[~gl.index.isin(matched_gl_indices | invalid_gl_indices | ambiguous_gl_indices)].copy()
    )
    regular_stock_without = _risk_columns(
        regular_stock_without,
        "stock_without_gl",
        config,
        "total_cost",
        input_policy=input_policy,
    )
    regular_gl_without = _risk_columns(
        regular_gl_without,
        "gl_without_stock",
        config,
        "amount",
        input_policy=input_policy,
    )
    if assignment.ambiguities:
        ambiguous_stock = _risk_columns(
            _expose_record_lineage(
                _ambiguity_frame(
                    stock,
                    assignment.ambiguities,
                    side="stock",
                    ambiguity_policy=resolved_ambiguity_policy,
                )
            ),
            "ambiguous_match",
            config,
            "total_cost",
            input_policy=input_policy,
        )
        ambiguous_gl = _risk_columns(
            _expose_record_lineage(
                _ambiguity_frame(
                    gl,
                    assignment.ambiguities,
                    side="gl",
                    ambiguity_policy=resolved_ambiguity_policy,
                )
            ),
            "ambiguous_match",
            config,
            "amount",
            input_policy=input_policy,
        )
        stock_without = pd.concat(
            [regular_stock_without, ambiguous_stock],
            ignore_index=True,
            sort=False,
        )
        gl_without = pd.concat(
            [regular_gl_without, ambiguous_gl],
            ignore_index=True,
            sort=False,
        )
    else:
        stock_without = regular_stock_without
        gl_without = regular_gl_without

    stock_without = _stable_output_order(stock_without, "record_instance_id", "move_id")
    gl_without = _stable_output_order(gl_without, "record_instance_id", "entry_id")
    value_differences = _stable_output_order(value_differences, "exception_id", "match_id")
    date_differences = _stable_output_order(date_differences, "exception_id", "match_id")
    reference_mismatches = _stable_output_order(reference_mismatches, "exception_id", "match_id")
    data_quality = _stable_output_order(data_quality, "exception_id", "record_instance_id", "field")

    exception_frames = [
        stock_without,
        gl_without,
        value_differences,
        date_differences,
        reference_mismatches,
        data_quality,
    ]
    non_empty_exceptions = [frame for frame in exception_frames if not frame.empty]
    all_exceptions = (
        pd.concat(non_empty_exceptions, ignore_index=True, sort=False)
        if non_empty_exceptions
        else pd.DataFrame(
            columns=[
                "exception_id",
                "exception_type",
                "exception_reason",
                "exception_title",
                "exception_explanation",
                "evidence_reference",
                "suggested_action",
                "severity",
                "ownership",
                "workflow_status",
                "risk_score",
                "risk_level",
            ],
        )
    )
    all_exceptions = _stable_output_order(all_exceptions, "exception_id", "exception_type", "evidence_reference")

    result_frames = {
        "matched_transactions": matched,
        "stock_without_gl": stock_without,
        "gl_without_stock": gl_without,
        "value_differences": value_differences,
        "date_differences": date_differences,
        "reference_mismatches": reference_mismatches,
        "data_quality_exceptions": data_quality,
    }
    summary = _summary_frame(result_frames)
    accounted_stock_count = len(matched) + len(stock_without) + len(invalid_stock_indices)
    accounted_gl_count = len(matched) + len(gl_without) + len(invalid_gl_indices)
    invariants: dict[str, int | bool] = {
        "stock_input_rows": len(stock),
        "gl_input_rows": len(gl),
        "invalid_stock_rows": len(invalid_stock_indices),
        "invalid_gl_rows": len(invalid_gl_indices),
        "accounted_stock_rows": accounted_stock_count,
        "accounted_gl_rows": accounted_gl_count,
        "record_accounting_ok": accounted_stock_count == len(stock) and accounted_gl_count == len(gl),
    }
    return StockGLReconciliationResult(
        matched_transactions=matched,
        stock_without_gl=stock_without,
        gl_without_stock=gl_without,
        value_differences=value_differences,
        date_differences=date_differences,
        reference_mismatches=reference_mismatches,
        data_quality_exceptions=data_quality,
        all_exceptions=all_exceptions,
        summary=summary,
        invariants=invariants,
        financial_input_policy=input_policy,
        record_identity_policy=RECORD_IDENTITY_POLICY,
        matching_ambiguity_policy=resolved_ambiguity_policy,
    )


def result_frames(result: StockGLReconciliationResult) -> dict[str, pd.DataFrame]:
    """Return stock-GL result frames for writing."""

    return {
        "summary": result.summary,
        "matched_transactions": result.matched_transactions,
        "stock_without_gl": result.stock_without_gl,
        "gl_without_stock": result.gl_without_stock,
        "value_differences": result.value_differences,
        "date_differences": result.date_differences,
        "reference_mismatches": result.reference_mismatches,
        "data_quality_exceptions": result.data_quality_exceptions,
        "all_exceptions": result.all_exceptions,
    }
