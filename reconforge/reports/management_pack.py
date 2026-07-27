"""Management pack generation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from typing import Any

import pandas as pd

from reconforge.close import close_summary_frame, load_close_checklist
from reconforge.config import ReconForgeConfig
from reconforge.io.excel import add_summary_chart, audit_metadata, write_excel_workbook
from reconforge.io.generated import GeneratedArtifactError, read_generated_json_document
from reconforge.io.writers import frame_to_records, write_json, write_report_frames
from reconforge.reconciliation.stock_gl import StockGLReconciliationResult
from reconforge.reconciliation.stock_gl import result_frames as stock_gl_frames
from reconforge.reconciliation.workorders import WorkorderReconciliationResult
from reconforge.reconciliation.workorders import result_frames as workorder_frames
from reconforge.reports.html import write_html_dashboard
from reconforge.reports.markdown import write_markdown_summary
from reconforge.reports.wip_aging import aging_summary
from reconforge.review.state import CERTIFICATION_COLUMNS, load_review_state, merge_review_state_with_exceptions
from reconforge.utils.money import CurrencyRegistry, InvalidAmountError, ResolvedCurrencyPolicy, parse_amount
from reconforge.validators import issues_to_frame, validate_input_directory


@dataclass(frozen=True)
class ManagementPackArtifacts:
    """Generated management pack artifact paths."""

    excel_path: Path
    json_path: Path
    markdown_path: Path
    html_path: Path
    csv_json_paths: list[Path]


def _to_decimal(value: object) -> Decimal:
    """Parse a strict, non-quantized decimal value for report math."""

    try:
        return parse_amount(value)
    except (InvalidAmountError, TypeError, ValueError) as exc:
        raise ValueError("Invalid amount value provided for report calculation.") from exc


def _exact_decimal_sum(amounts: list[Decimal]) -> Decimal:
    if not amounts:
        return Decimal("0")
    max_adjusted = max((value.adjusted() for value in amounts if value), default=0)
    min_exponent = min(int(value.as_tuple().exponent) for value in amounts)
    carry_digits = len(str(len(amounts))) + 1
    with localcontext() as context:
        context.prec = max(28, max_adjusted - min_exponent + carry_digits + 2)
        return sum(amounts, Decimal("0"))


def _sum_decimal_series(values: pd.Series[Any]) -> Decimal:
    """Sum valid finance values exactly; callers must expose omitted invalid rows."""

    amounts = [parsed for parsed in (_to_optional_decimal(value) for value in values) if parsed is not None]
    return _exact_decimal_sum(amounts)


def _sum_required_decimal_series(values: pd.Series[Any]) -> Decimal:
    """Sum a required finance series, rejecting missing or malformed values."""

    return _exact_decimal_sum([_to_decimal(value) for value in values])


def _default_report_currency_policy() -> ResolvedCurrencyPolicy:
    return CurrencyRegistry.resolve("USD")


def _quantize_report_amount(value: Decimal, policy: ResolvedCurrencyPolicy) -> Decimal:
    """Apply the captured registry policy with enough local precision."""

    spec = policy.spec
    quantum = Decimal("1").scaleb(-spec.minor_units)
    integer_digits = max(1, value.adjusted() + 1) if value else 1
    required_precision = max(28, len(value.as_tuple().digits) + 2, integer_digits + spec.minor_units + 2)
    with localcontext() as context:
        context.prec = required_precision
        return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _amount_policy_fields(policy: ResolvedCurrencyPolicy) -> dict[str, object]:
    spec = policy.spec
    return {
        "currency": spec.code,
        "currency_minor_units": spec.minor_units,
        "currency_rounding_policy": spec.rounding_policy,
        "currency_policy_digest": policy.policy_digest,
    }


def _currency_policy_payload(policy: ResolvedCurrencyPolicy) -> dict[str, object]:
    return {
        **_amount_policy_fields(policy),
        "aggregation_policy": "single-currency-only-no-implicit-fx",
        "missing_currency_policy": "configured-output-currency-compatibility",
        "currency_registry_digest": policy.registry_digest,
        "currency_registry_version": policy.registry_version,
    }


def _validate_report_currency_scope(
    frames: list[pd.DataFrame],
    policy: ResolvedCurrencyPolicy,
) -> None:
    """Reject cross-currency aggregation because this report performs no FX conversion."""

    explicit_codes: set[str] = set()
    for frame in frames:
        if frame.empty or "currency" not in frame.columns:
            continue
        for raw_value in frame["currency"]:
            if raw_value is None or pd.isna(raw_value) or not str(raw_value).strip():
                continue
            try:
                explicit_codes.add(CurrencyRegistry.resolve(str(raw_value)).spec.code)
            except InvalidAmountError as exc:
                raise ValueError("Management pack contains an invalid or unregistered currency.") from exc
    if explicit_codes - {policy.spec.code}:
        raise ValueError(
            "Management pack cannot aggregate currencies that differ from output_currency without explicit FX conversion.",
        )


def _attach_amount_policy(frame: pd.DataFrame, policy: ResolvedCurrencyPolicy) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return frame.assign(**_amount_policy_fields(policy))


def _executive_summary(
    stock_result: StockGLReconciliationResult,
    workorder_result: WorkorderReconciliationResult,
    wip_aging: pd.DataFrame,
    *,
    currency_policy: ResolvedCurrencyPolicy | None = None,
) -> pd.DataFrame:
    policy = currency_policy or _default_report_currency_policy()
    matched_amount = _sum_required_decimal_series(
        stock_result.matched_transactions.get("stock_amount", pd.Series(dtype=object)),
    )
    unmatched_stock_amount = _sum_required_decimal_series(
        stock_result.stock_without_gl.get("total_cost", pd.Series(dtype=object)),
    )
    unmatched_gl_amount = _sum_required_decimal_series(
        stock_result.gl_without_stock.get("amount", pd.Series(dtype=object)),
    )
    exception_count = len(stock_result.all_exceptions) + len(workorder_result.all_exceptions)
    critical_count = int(
        pd.concat([stock_result.all_exceptions, workorder_result.all_exceptions], ignore_index=True, sort=False)
        .get("risk_level", pd.Series(dtype=str))
        .astype(str)
        .eq("Critical")
        .sum(),
    )
    return pd.DataFrame(
        [
            {
                "metric": "matched_amount",
                "value": _quantize_report_amount(matched_amount, policy),
                **_amount_policy_fields(policy),
            },
            {
                "metric": "unmatched_stock_amount",
                "value": _quantize_report_amount(unmatched_stock_amount, policy),
                **_amount_policy_fields(policy),
            },
            {
                "metric": "unmatched_gl_amount",
                "value": _quantize_report_amount(unmatched_gl_amount, policy),
                **_amount_policy_fields(policy),
            },
            {"metric": "exception_count", "value": exception_count},
            {"metric": "critical_risk_count", "value": critical_count},
            {"metric": "open_wip_orders", "value": len(wip_aging)},
        ],
    )


def _to_optional_decimal(value: object) -> Decimal | None:
    """Parse a strict numeric value, returning None when the value is malformed."""

    try:
        return parse_amount(value)
    except (InvalidAmountError, TypeError, ValueError):
        return None


def _risk_score_series(frame: pd.DataFrame) -> pd.Series:
    return pd.Series(
        [_to_optional_decimal(value) for value in frame.get("risk_score", pd.Series([None] * len(frame), index=frame.index))],
        index=frame.index,
    )


def _high_risk_exceptions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    mask = _risk_score_series(frame).map(lambda value: value is not None and value >= Decimal("61"))
    return frame[mask].copy()


def _risk_scoring(stock_result: StockGLReconciliationResult, workorder_result: WorkorderReconciliationResult) -> pd.DataFrame:
    combined = pd.concat([stock_result.all_exceptions, workorder_result.all_exceptions], ignore_index=True, sort=False)
    if combined.empty or "risk_level" not in combined.columns:
        return pd.DataFrame(columns=["risk_level", "exception_count"])
    return combined.groupby("risk_level", as_index=False).agg(exception_count=("risk_level", "count"))


def _amount_impact_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series([None] * len(frame), index=frame.index, dtype=object)
    amount = pd.Series([None] * len(frame), index=frame.index, dtype=object)
    for field in ("amount_impact", "total_cost", "amount", "total_price", "actual_cost", "estimated_cost", "invoice_amount"):
        if field not in frame.columns:
            continue
        values = pd.Series(
            [
                parsed.copy_abs() if parsed is not None else None
                for parsed in (_to_optional_decimal(value) for value in frame[field])
            ],
            index=frame.index,
            dtype=object,
        )
        amount = amount.mask(amount.isna(), values)
    return amount


def _severity_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=str)
    severity = pd.Series([""] * len(frame), index=frame.index)
    for field in ("risk_level", "severity"):
        if field in frame.columns:
            severity = severity.mask(severity.str.strip().eq(""), frame[field].astype(str))
    return severity.str.lower()


def _top_control_themes(combined: pd.DataFrame) -> pd.DataFrame:
    if combined.empty:
        return pd.DataFrame(
            columns=["control_theme", "exception_count", "amount_impact", "unquantified_amount_count"],
        )
    theme_column = "exception_type" if "exception_type" in combined.columns else "rule_name" if "rule_name" in combined.columns else ""
    if not theme_column:
        return pd.DataFrame(
            columns=["control_theme", "exception_count", "amount_impact", "unquantified_amount_count"],
        )
    themed = combined.assign(
        control_theme=combined[theme_column].astype(str),
        amount_impact=_amount_impact_series(combined),
    )
    themed = themed.assign(unquantified_amount=themed["amount_impact"].isna())
    return (
        themed.groupby("control_theme", as_index=False)
        .agg(
            exception_count=("control_theme", "count"),
            amount_impact=("amount_impact", _sum_decimal_series),
            unquantified_amount_count=("unquantified_amount", "sum"),
        )
        .sort_values(["exception_count", "amount_impact"], ascending=False)
        .head(5)
    )


def _json_payload(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = read_generated_json_document(path).payload
    except GeneratedArtifactError:
        return {}
    return payload


def _recurring_exception_count(output_dir: Path) -> int | str:
    for path in [output_dir / "period_comparison.json", output_dir / "period_comparison" / "period_comparison.json"]:
        payload = _json_payload(path)
        if not payload:
            continue
        recurring = payload.get("recurring_exceptions")
        if isinstance(recurring, list):
            return len(recurring)
        summary = payload.get("summary")
        if isinstance(summary, list):
            for row in summary:
                if isinstance(row, dict) and row.get("metric") == "recurring_exceptions":
                    try:
                        return int(row.get("value", 0))
                    except (TypeError, ValueError):
                        return "not_available"
    return "not_available"


def _close_completion_rate(output_dir: Path) -> Decimal | str:
    for path in [output_dir / "close", output_dir]:
        try:
            summary = close_summary_frame(load_close_checklist(path))
        except (FileNotFoundError, ValueError):
            continue
        row = summary[summary["metric"].eq("completion_rate_pct")]
        if not row.empty:
            try:
                return parse_amount(row.iloc[0]["value"])
            except (TypeError, ValueError, InvalidAmountError):
                return "not_available"
    return "not_available"


def _evidence_coverage_pct(high_critical: int, output_dir: Path) -> float | str:
    if high_critical == 0:
        return 100.0
    payload = _json_payload(output_dir / "evidence" / "evidence_index.json")
    if not payload:
        return "not_available"
    case_count = payload.get("case_count")
    if isinstance(case_count, (int, float, str)):
        try:
            evidence_cases = int(case_count)
        except ValueError:
            evidence_cases = 0
    else:
        cases = payload.get("cases")
        evidence_cases = len(cases) if isinstance(cases, list) else 0
    return round(min((evidence_cases / high_critical) * 100, 100.0), 2)


def _control_value_summary(
    combined: pd.DataFrame,
    wip_aging: pd.DataFrame,
    output_dir: Path,
    *,
    currency_policy: ResolvedCurrencyPolicy | None = None,
) -> pd.DataFrame:
    policy = currency_policy or _default_report_currency_policy()
    total_exceptions = len(combined)
    merged = merge_review_state_with_exceptions(combined, load_review_state(output_dir / "review_state.json"))
    status = merged.get("status", pd.Series(["New"] * len(merged))).astype(str)
    status_lower = status.str.lower()
    severity = _severity_series(combined)
    high_critical_mask = severity.isin({"high", "critical"})
    high_critical = int(high_critical_mask.sum())
    unresolved = int((~status.isin({"Resolved", "Accepted Risk"})).sum()) if total_exceptions else 0
    unresolved_high_risk = int((high_critical_mask & ~status_lower.isin({"resolved", "accepted risk"})).sum()) if total_exceptions else 0
    accepted_risk = int(status.eq("Accepted Risk").sum())
    escalated = int(status.eq("Escalated").sum())
    reviewed = int(status.ne("New").sum())
    review_completion_rate = round((reviewed / total_exceptions) * 100, 2) if total_exceptions else 0.0
    certification_status = merged.get("certification_status", pd.Series([""] * len(merged))).astype(str)
    certified_count = int(certification_status.isin({"Prepared", "Reviewed", "Accepted Risk"}).sum())
    exception_amounts = _amount_impact_series(combined)
    unquantified_exception_count = int(exception_amounts.isna().sum())
    estimated_value_impact = (
        _quantize_report_amount(_sum_decimal_series(exception_amounts), policy)
        if total_exceptions
        else _quantize_report_amount(Decimal("0"), policy)
    )
    wip_source = wip_aging.get(
        "actual_cost",
        wip_aging.get("estimated_cost", pd.Series([None] * len(wip_aging), index=wip_aging.index)),
    )
    wip_amounts = (
        pd.Series([_to_optional_decimal(value) for value in wip_source], index=wip_aging.index)
        if isinstance(wip_source, pd.Series)
        else pd.Series([_to_optional_decimal(wip_source)])
    )
    unquantified_wip_count = int(wip_amounts.isna().sum()) if not wip_aging.empty else 0
    if not wip_aging.empty:
        wip_exposure = _quantize_report_amount(_sum_decimal_series(wip_amounts), policy)
    else:
        wip_exposure = _quantize_report_amount(Decimal("0"), policy)
    return pd.DataFrame(
        [
            {"metric": "total_exceptions", "value": total_exceptions, "meaning": "All detected reconciliation and operational exceptions."},
            {"metric": "high_or_critical_exceptions", "value": high_critical, "meaning": "Exceptions requiring priority finance, audit, or operations review."},
            {"metric": "unresolved_exceptions", "value": unresolved, "meaning": "Exceptions not yet resolved or formally accepted as risk."},
            {"metric": "unresolved_high_risk_count", "value": unresolved_high_risk, "meaning": "High or Critical exceptions not yet resolved or accepted as risk."},
            {"metric": "accepted_risk_count", "value": accepted_risk, "meaning": "Exceptions explicitly accepted with documented rationale."},
            {"metric": "escalated_count", "value": escalated, "meaning": "Exceptions assigned for escalation."},
            {
                "metric": "unquantified_exception_count",
                "value": unquantified_exception_count,
                "meaning": "Exceptions with no valid available amount; excluded from estimated value impact and never converted to zero.",
            },
            {
                "metric": "unquantified_wip_count",
                "value": unquantified_wip_count,
                "meaning": "Open WIP rows with no valid cost; excluded from WIP exposure and never converted to zero.",
            },
            {
                "metric": "estimated_value_impact",
                "value": estimated_value_impact,
                "meaning": "Simple sum of available exception amount fields; not a savings claim.",
                **_amount_policy_fields(policy),
            },
            {
                "metric": "wip_exposure",
                "value": wip_exposure,
                "meaning": "Available WIP cost exposure from open work-order aging data.",
                **_amount_policy_fields(policy),
            },
            {"metric": "review_completion_rate_pct", "value": review_completion_rate, "meaning": "Percent of exceptions with a status other than New."},
            {"metric": "certified_review_count", "value": certified_count, "meaning": "Exceptions with workflow certification metadata. This is not a legal sign-off."},
            {"metric": "recurring_exception_count", "value": _recurring_exception_count(output_dir), "meaning": "Recurring exceptions from a local period comparison report when available."},
            {"metric": "close_checklist_completion_pct", "value": _close_completion_rate(output_dir), "meaning": "Local close checklist completion when a close checklist exists."},
            {"metric": "evidence_coverage_high_critical_pct", "value": _evidence_coverage_pct(high_critical, output_dir), "meaning": "High/Critical evidence coverage when a local evidence index exists."},
        ],
    )


def _risk_matrix(combined: pd.DataFrame) -> pd.DataFrame:
    if combined.empty:
        return pd.DataFrame(
            columns=["risk_level", "exception_type", "exception_count", "amount_impact", "unquantified_amount_count"],
        )
    matrix = combined.assign(amount_impact=_amount_impact_series(combined))
    matrix = matrix.assign(unquantified_amount=matrix["amount_impact"].isna())
    group_cols = [column for column in ["risk_level", "exception_type"] if column in matrix.columns]
    if not group_cols:
        return pd.DataFrame(
            columns=["risk_level", "exception_type", "exception_count", "amount_impact", "unquantified_amount_count"],
        )
    return matrix.groupby(group_cols, as_index=False).agg(
        exception_count=("exception_type", "count"),
        amount_impact=("amount_impact", _sum_decimal_series),
        unquantified_amount_count=("unquantified_amount", "sum"),
    )


def _control_effectiveness(stock_result: StockGLReconciliationResult, workorder_result: WorkorderReconciliationResult) -> pd.DataFrame:
    total_stock = len(stock_result.matched_transactions) + len(stock_result.stock_without_gl)
    match_rate = len(stock_result.matched_transactions) / total_stock if total_stock else 0.0
    return pd.DataFrame(
        [
            {"control": "Stock to GL matching", "metric": "match_rate", "value": round(match_rate, 4)},
            {"control": "Stock to GL matching", "metric": "unmatched_stock_count", "value": len(stock_result.stock_without_gl)},
            {"control": "Stock to GL matching", "metric": "unmatched_gl_count", "value": len(stock_result.gl_without_stock)},
            {"control": "Work order governance", "metric": "exception_count", "value": len(workorder_result.all_exceptions)},
        ],
    )


def _configuration_used(config: ReconForgeConfig) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"parameter": "amount_tolerance", "value": config.amount_tolerance},
            {"parameter": "date_tolerance_days", "value": config.date_tolerance_days},
            {"parameter": "matching_ambiguity_policy", "value": config.matching_ambiguity_policy},
            {"parameter": "output_currency", "value": config.output_currency},
            {"parameter": "company_name", "value": config.company_name},
            {"parameter": "report_title", "value": config.report_title},
        ],
    )


def _certification_register(combined: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    merged = merge_review_state_with_exceptions(combined, load_review_state(output_dir / "review_state.json"))
    columns = [
        "exception_id",
        "status",
        "reviewer",
        *CERTIFICATION_COLUMNS,
        "severity",
        "exception_type",
        "amount_impact",
        "source_file",
    ]
    for column in columns:
        if column not in merged.columns:
            merged[column] = ""
    return merged[columns].copy()


def _recommended_actions(stock_result: StockGLReconciliationResult, workorder_result: WorkorderReconciliationResult, wip_aging: pd.DataFrame) -> pd.DataFrame:
    actions = [
        {"priority": "High", "owner": "Finance", "action": "Clear stock movements without GL postings before period close.", "trigger_count": len(stock_result.stock_without_gl)},
        {"priority": "High", "owner": "Stores", "action": "Investigate GL expenses without matching stock movement evidence.", "trigger_count": len(stock_result.gl_without_stock)},
        {"priority": "High", "owner": "Workshop", "action": "Resolve direct purchase-and-fit cases with receipt, issue, and approval evidence.", "trigger_count": len(workorder_result.direct_purchase_fitting_risk)},
        {"priority": "Medium", "owner": "Workshop", "action": "Collect or document old-part returns for controlled categories.", "trigger_count": len(workorder_result.old_part_return_missing)},
        {"priority": "Medium", "owner": "Finance Controller", "action": "Review WIP older than 90 days and agree closure or provisioning actions.", "trigger_count": int(wip_aging["aging_days"].gt(90).sum()) if not wip_aging.empty else 0},
    ]
    return pd.DataFrame(actions)


def _audit_log(config: ReconForgeConfig, input_path: Path) -> pd.DataFrame:
    metadata = audit_metadata(config.company_name, config.report_title, config.output_currency)
    metadata["input_path"] = str(input_path)
    metadata["amount_tolerance"] = str(config.amount_tolerance)
    metadata["date_tolerance_days"] = str(config.date_tolerance_days)
    metadata["matching_ambiguity_policy"] = config.matching_ambiguity_policy
    return pd.DataFrame([metadata])


def management_summary_dict(executive_summary: pd.DataFrame) -> dict[str, Decimal | float | int | str]:
    """Convert executive summary frame to a dictionary."""

    summary: dict[str, Decimal | float | int | str] = {}
    for _, row in executive_summary.iterrows():
        summary[str(row["metric"])] = row["value"]
    return summary


def generate_management_pack(
    input_path: Path,
    output_dir: Path,
    config: ReconForgeConfig,
    stock_result: StockGLReconciliationResult,
    workorder_result: WorkorderReconciliationResult,
    wip_aging: pd.DataFrame,
) -> ManagementPackArtifacts:
    """Generate the full Excel, JSON, CSV, Markdown, and HTML management pack."""

    currency_policy = CurrencyRegistry.resolve(config.output_currency)
    combined_exceptions = pd.concat(
        [stock_result.all_exceptions, workorder_result.all_exceptions],
        ignore_index=True,
        sort=False,
    )
    _validate_report_currency_scope(
        [
            stock_result.matched_transactions,
            stock_result.stock_without_gl,
            stock_result.gl_without_stock,
            combined_exceptions,
            wip_aging,
        ],
        currency_policy,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    executive_summary = _executive_summary(
        stock_result,
        workorder_result,
        wip_aging,
        currency_policy=currency_policy,
    )
    risk_scoring = _risk_scoring(stock_result, workorder_result)
    recommended_actions = _recommended_actions(stock_result, workorder_result, wip_aging)
    wip_summary = aging_summary(wip_aging)
    audit_log = _audit_log(config, input_path)
    control_value_summary = _control_value_summary(
        combined_exceptions,
        wip_aging,
        output_dir,
        currency_policy=currency_policy,
    )
    top_control_themes = _attach_amount_policy(_top_control_themes(combined_exceptions), currency_policy)
    risk_matrix = _attach_amount_policy(_risk_matrix(combined_exceptions), currency_policy)
    high_risk = _high_risk_exceptions(combined_exceptions) if not combined_exceptions.empty else pd.DataFrame()
    data_quality_warnings = issues_to_frame(validate_input_directory(input_path))

    sheets = {
        "Executive Summary": executive_summary,
        "Control Value Summary": control_value_summary,
        "KPI Dashboard": executive_summary,
        "Certification Metadata": _certification_register(combined_exceptions, output_dir),
        "Reconciliation Summary": stock_result.summary,
        "Stock vs GL Mismatch": stock_result.all_exceptions,
        "Stock Without GL": stock_result.stock_without_gl,
        "GL Without Stock": stock_result.gl_without_stock,
        "Amount Variances": stock_result.value_differences,
        "Work Order Exceptions": workorder_result.all_exceptions,
        "WIP Aging": wip_aging,
        "Control Pack Results": pd.DataFrame(),
        "High Risk Exceptions": high_risk,
        "Evidence Register": pd.DataFrame(),
        "WIP Aging Summary": wip_summary,
        "Risk Scoring": risk_scoring,
        "Risk Matrix": risk_matrix,
        "Top Control Themes": top_control_themes,
        "Control Effectiveness": _control_effectiveness(stock_result, workorder_result),
        "Recommended Actions": recommended_actions,
        "Audit Log": audit_log,
        "Data Quality Warnings": data_quality_warnings,
        "Configuration Used": _configuration_used(config),
    }
    excel_metadata = audit_metadata(config.company_name, config.report_title, config.output_currency)
    excel_metadata["financial_input_policy"] = stock_result.financial_input_policy
    excel_metadata["record_identity_policy"] = stock_result.record_identity_policy
    excel_metadata["matching_ambiguity_policy"] = stock_result.matching_ambiguity_policy
    excel_path = write_excel_workbook(
        sheets,
        output_dir / "management_pack.xlsx",
        metadata=excel_metadata,
    )
    add_summary_chart(excel_path, "Risk Scoring", "Exceptions by Risk Level")
    add_summary_chart(excel_path, "WIP Aging Summary", "WIP Aging Buckets")

    all_frames = {
        **{f"stock_gl_{name}": frame for name, frame in stock_gl_frames(stock_result).items()},
        **{f"workorders_{name}": frame for name, frame in workorder_frames(workorder_result).items()},
        "wip_aging": wip_aging,
        "wip_aging_summary": wip_summary,
    }
    csv_json_paths = write_report_frames(all_frames, output_dir, "management_pack")

    payload: dict[str, Any] = {
        "schema_version": 4,
        "financial_input_policy": stock_result.financial_input_policy,
        "record_identity_policy": stock_result.record_identity_policy,
        "matching_ambiguity_policy": stock_result.matching_ambiguity_policy,
        "currency_policy": _currency_policy_payload(currency_policy),
        "executive_summary": frame_to_records(executive_summary),
        "control_value_summary": frame_to_records(control_value_summary),
        "certification_metadata": frame_to_records(_certification_register(combined_exceptions, output_dir)),
        "top_control_themes": frame_to_records(top_control_themes),
        "risk_scoring": frame_to_records(risk_scoring),
        "stock_gl_summary": frame_to_records(stock_result.summary),
        "workorder_summary": frame_to_records(workorder_result.summary),
        "wip_aging": frame_to_records(wip_aging),
        "top_exceptions": frame_to_records(combined_exceptions.sort_values("risk_score", ascending=False).head(25)) if not combined_exceptions.empty and "risk_score" in combined_exceptions.columns else [],
    }
    json_path = write_json(payload, output_dir, "management_pack")
    critical_count = int(combined_exceptions.get("risk_level", pd.Series(dtype=str)).astype(str).eq("Critical").sum()) if not combined_exceptions.empty else 0
    markdown_path = write_markdown_summary(
        output_dir / "summary.md",
        config,
        stock_result.summary,
        workorder_result.summary,
        wip_aging,
        critical_count,
    )
    write_markdown_summary(
        output_dir / "management_summary.md",
        config,
        stock_result.summary,
        workorder_result.summary,
        wip_aging,
        critical_count,
    )
    html_path = write_html_dashboard(
        output_dir / "dashboard.html",
        config,
        management_summary_dict(executive_summary),
        combined_exceptions.sort_values("risk_score", ascending=False) if not combined_exceptions.empty and "risk_score" in combined_exceptions.columns else combined_exceptions,
        wip_aging,
        control_value_summary=control_value_summary,
        top_control_themes=top_control_themes,
        recommended_actions=recommended_actions,
    )
    write_html_dashboard(
        output_dir / "executive_report.html",
        config,
        management_summary_dict(executive_summary),
        combined_exceptions.sort_values("risk_score", ascending=False) if not combined_exceptions.empty and "risk_score" in combined_exceptions.columns else combined_exceptions,
        wip_aging,
        control_value_summary=control_value_summary,
        top_control_themes=top_control_themes,
        recommended_actions=recommended_actions,
    )

    return ManagementPackArtifacts(
        excel_path=excel_path,
        json_path=json_path,
        markdown_path=markdown_path,
        html_path=html_path,
        csv_json_paths=csv_json_paths,
    )
