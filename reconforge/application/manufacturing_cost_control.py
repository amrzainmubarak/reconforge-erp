"""Application boundary for local manufacturing cost-control exports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from reconforge.domain.manufacturing_cost_control import (
    ManufacturingControlError,
    MaterialIssue,
    ProductionCompletion,
    ProductionOrder,
    ScrapEvent,
    run_manufacturing_cost_control,
    verify_manufacturing_payload,
)
from reconforge.io.records import RecordIngressError, read_json_record_document
from reconforge.utils.money import Money, Quantity


def _required(record: dict[str, Any], key: str) -> Any:
    if key not in record:
        raise ManufacturingControlError(f"manufacturing input is missing {key}.")
    return record[key]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quantity(value: object, unit: object) -> Quantity:
    if isinstance(value, (bool, float)):
        raise ManufacturingControlError("manufacturing quantity must use exact decimal text.")
    if not isinstance(unit, str) or not unit.strip():
        raise ManufacturingControlError("manufacturing quantity unit is invalid.")
    try:
        return Quantity(cast(Any, value), unit)
    except Exception as exc:
        raise ManufacturingControlError("manufacturing quantity is invalid.") from exc


def _read_records(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        document = read_json_record_document(path, envelope_keys=("records", "data"))
    except RecordIngressError as exc:
        raise ManufacturingControlError(f"manufacturing input rejected ({exc.code}).") from exc
    return list(document.records), document.checksum_sha256


def _read_orders(path: Path) -> tuple[tuple[ProductionOrder, ...], str]:
    records, digest = _read_records(path)
    try:
        orders = tuple(
            ProductionOrder(
                order_id=_required(record, "order_id"),
                product_id=_required(record, "product_id"),
                planned_quantity=_quantity(_required(record, "planned_quantity"), _required(record, "unit")),
                standard_unit_cost=Money.from_exact(_required(record, "standard_unit_cost"), _required(record, "currency")),
                source_reference=_required(record, "source_reference"),
            )
            for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManufacturingControlError("production-order input does not match the closed record contract.") from exc
    return orders, digest


def _read_issues(path: Path) -> tuple[tuple[MaterialIssue, ...], str]:
    records, digest = _read_records(path)
    try:
        issues = tuple(
            MaterialIssue(
                issue_id=_required(record, "issue_id"),
                order_id=_required(record, "order_id"),
                item_id=_required(record, "item_id"),
                quantity=_quantity(_required(record, "quantity"), _required(record, "unit")),
                unit_cost=Money.from_exact(_required(record, "unit_cost"), _required(record, "currency")),
                source_reference=_required(record, "source_reference"),
            )
            for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManufacturingControlError("material-issue input does not match the closed record contract.") from exc
    return issues, digest


def _read_completions(path: Path) -> tuple[tuple[ProductionCompletion, ...], str]:
    records, digest = _read_records(path)
    try:
        completions = tuple(
            ProductionCompletion(
                completion_id=_required(record, "completion_id"),
                order_id=_required(record, "order_id"),
                completion_date=_required(record, "completion_date"),
                quantity=_quantity(_required(record, "quantity"), _required(record, "unit")),
                actual_cost=Money.from_exact(_required(record, "actual_cost"), _required(record, "currency")),
                source_reference=_required(record, "source_reference"),
            )
            for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManufacturingControlError("completion input does not match the closed record contract.") from exc
    return completions, digest


def _read_scrap(path: Path) -> tuple[tuple[ScrapEvent, ...], str]:
    records, digest = _read_records(path)
    try:
        scrap = tuple(
            ScrapEvent(
                scrap_id=_required(record, "scrap_id"),
                order_id=_required(record, "order_id"),
                scrap_date=_required(record, "scrap_date"),
                quantity=_quantity(_required(record, "quantity"), _required(record, "unit")),
                reason=_required(record, "reason"),
                source_reference=_required(record, "source_reference"),
            )
            for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManufacturingControlError("scrap input does not match the closed record contract.") from exc
    return scrap, digest


def run_manufacturing_cost_control_files(
    orders_path: Path,
    issues_path: Path,
    completions_path: Path,
    scrap_path: Path,
    *,
    currency: str,
    tolerance: str,
    max_scrap_quantity: str,
    unit: str = "PCS",
) -> Any:
    """Run the local production-order cost and quantity control."""

    orders, orders_digest = _read_orders(orders_path)
    issues, issues_digest = _read_issues(issues_path)
    completions, completions_digest = _read_completions(completions_path)
    scrap, scrap_digest = _read_scrap(scrap_path)
    try:
        amount_tolerance = Money.from_exact(tolerance, currency)
        scrap_limit = _quantity(max_scrap_quantity, unit)
    except Exception as exc:
        raise ManufacturingControlError("manufacturing control policy is invalid.") from exc
    return run_manufacturing_cost_control(
        orders,
        issues,
        completions,
        scrap,
        amount_tolerance=amount_tolerance,
        max_scrap_quantity=scrap_limit,
        input_digests=(orders_digest, issues_digest, completions_digest, scrap_digest, _sha256(orders_path), _sha256(issues_path), _sha256(completions_path), _sha256(scrap_path)),
    )


def write_manufacturing_report(run: Any, output_path: Path) -> None:
    payload = run.to_dict()
    payload["artifact_type"] = "reconforge-manufacturing-cost-control"
    payload["artifact_digest"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_manufacturing_report(path: Path) -> dict[str, Any]:
    from reconforge.io.structured import StructuredDocumentError, read_json_document

    try:
        payload = read_json_document(path)
    except (OSError, UnicodeError, StructuredDocumentError) as exc:
        raise ManufacturingControlError("manufacturing report cannot be read.") from exc
    if not isinstance(payload, dict) or payload.get("artifact_type") != "reconforge-manufacturing-cost-control":
        raise ManufacturingControlError("manufacturing report artifact type is invalid.")
    artifact_digest = payload.get("artifact_digest")
    without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    expected = hashlib.sha256(
        json.dumps(without_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    if not isinstance(artifact_digest, str) or artifact_digest != expected:
        raise ManufacturingControlError("manufacturing report digest verification failed.")
    verify_manufacturing_payload(payload)
    return payload


__all__ = ["run_manufacturing_cost_control_files", "verify_manufacturing_report", "write_manufacturing_report"]
