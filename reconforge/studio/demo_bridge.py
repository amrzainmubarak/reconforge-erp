"""Build a versioned, synthetic-only data contract for the modern Studio preview."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconforge.enterprise_demo import SYNTHETIC_DATA_MARKER
from reconforge.io.writers import json_default

STUDIO_OVERVIEW_SCHEMA_VERSION = 1
STUDIO_EXCEPTION_QUEUE_SCHEMA_VERSION = 1
STUDIO_EVIDENCE_BINDER_SCHEMA_VERSION = 1
STUDIO_INVENTORY_CONTROL_SCHEMA_VERSION = 1
STUDIO_EXCEPTION_QUEUE_FILENAME = "studio-exceptions.json"
STUDIO_EVIDENCE_BINDER_FILENAME = "studio-evidence.json"
STUDIO_INVENTORY_CONTROL_FILENAME = "studio-inventory.json"
MAX_SOURCE_FILE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_RECORDS = 100_000
MAX_CONTRACT_TEXT_LENGTH = 2_000
RISK_RATINGS = ("critical", "high", "medium", "low")
EXPECTED_SOURCE_FILES = {
    "manifest": Path("demo_manifest.json"),
    "entities": Path("sample_entities.json"),
    "periods": Path("sample_periods.json"),
    "close_tasks": Path("sample_close_tasks.json"),
    "metrics": Path("reports/dashboard_metrics.json"),
    "exceptions": Path("reports/unified_exceptions.json"),
    "evidence": Path("reports/evidence_registry.json"),
}
OPTIONAL_INVENTORY_SOURCE_FILE = Path("sample_inventory_control.json")

METRIC_DEFINITIONS = {
    "close_completion": ("Close completion", "percent", "positive"),
    "unresolved_high_risk_exceptions": ("High-risk exceptions", "count", "critical"),
    "evidence_coverage": ("Evidence coverage", "percent", "positive"),
    "match_rate": ("Match rate", "percent", "positive"),
    "control_effectiveness": ("Control effectiveness", "percent", "warning"),
    "period_readiness": ("Period readiness", "percent", "warning"),
    "review_aging": ("Review aging", "days", "neutral"),
    "exception_aging": ("Exception aging", "days", "neutral"),
}


class StudioDemoBridgeError(ValueError):
    """Raised for safe, user-facing Studio demo bridge errors."""


@dataclass(frozen=True)
class StudioDemoBundle:
    """Paths written for the modern Studio synthetic workspace."""

    overview_path: Path
    exception_queue_path: Path
    evidence_binder_path: Path
    inventory_control_path: Path

    @property
    def paths(self) -> tuple[Path, Path, Path, Path]:
        return (
            self.overview_path,
            self.exception_queue_path,
            self.evidence_binder_path,
            self.inventory_control_path,
        )


def build_studio_demo_data(source_path: Path | str, output_path: Path | str) -> Path:
    """Create a deterministic Studio overview contract from a synthetic demo package."""

    source_dir = _safe_source_dir(source_path)
    destination = _safe_output_file(output_path)
    try:
        payloads = _load_source_payloads(source_dir)
        payload = _build_payload(payloads)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json_write(destination, payload)
    except StudioDemoBridgeError:
        raise
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise StudioDemoBridgeError("Unable to build the synthetic Studio data contract.") from exc
    return destination


def build_studio_demo_bundle(source_path: Path | str, output_path: Path | str) -> StudioDemoBundle:
    """Create the overview, exception, evidence, and inventory contracts."""

    source_dir = _safe_source_dir(source_path)
    overview_path = _safe_output_file(output_path)
    exception_queue_path = overview_path.with_name(STUDIO_EXCEPTION_QUEUE_FILENAME)
    evidence_binder_path = overview_path.with_name(STUDIO_EVIDENCE_BINDER_FILENAME)
    inventory_control_path = overview_path.with_name(STUDIO_INVENTORY_CONTROL_FILENAME)
    try:
        payloads = _load_source_payloads(source_dir)
        overview = _build_payload(payloads)
        exceptions = _build_exception_queue_payload(payloads)
        evidence = _build_evidence_binder_payload(payloads, overview)
        inventory = _build_inventory_control_payload(payloads)
        overview_path.parent.mkdir(parents=True, exist_ok=True)
        for path, payload in (
            (overview_path, overview),
            (exception_queue_path, exceptions),
            (evidence_binder_path, evidence),
            (inventory_control_path, inventory),
        ):
            _atomic_json_write(path, payload)
    except StudioDemoBridgeError:
        raise
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise StudioDemoBridgeError("Unable to build the synthetic Studio data bundle.") from exc
    return StudioDemoBundle(
        overview_path=overview_path,
        exception_queue_path=exception_queue_path,
        evidence_binder_path=evidence_binder_path,
        inventory_control_path=inventory_control_path,
    )


def _load_source_payloads(source_dir: Path) -> dict[str, dict[str, Any]]:
    payloads = {
        name: _read_object(_source_file(source_dir, relative_path))
        for name, relative_path in EXPECTED_SOURCE_FILES.items()
    }
    optional_path = source_dir / OPTIONAL_INVENTORY_SOURCE_FILE
    if optional_path.is_symlink():
        raise StudioDemoBridgeError("Synthetic inventory demo file must not be a symlink.")
    if optional_path.exists():
        payloads["inventory"] = _read_object(_source_file(source_dir, OPTIONAL_INVENTORY_SOURCE_FILE))
    else:
        manifest = payloads["manifest"]
        payloads["inventory"] = {
            "synthetic_data_only": True,
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
            "generated_at": manifest.get("generated_at", ""),
            "records": [],
        }
    return payloads


def _build_payload(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    manifest = payloads["manifest"]
    _require_synthetic_payload(manifest, label="demo manifest")
    if manifest.get("local_first") is not True or manifest.get("external_calls") is not False:
        raise StudioDemoBridgeError("Studio data bridge accepts local-first demo packages without external calls only.")
    for name in ("entities", "periods", "close_tasks", "metrics", "exceptions", "evidence", "inventory"):
        _require_synthetic_payload(payloads[name], label=name.replace("_", " "))

    entities = _records(payloads["entities"], label="entities")
    periods = _records(payloads["periods"], label="periods")
    close_tasks = _records(payloads["close_tasks"], label="close tasks")
    metrics = _records(payloads["metrics"], label="metrics")
    exceptions = _records(payloads["exceptions"], label="exceptions")
    evidence = _records(payloads["evidence"], label="evidence")

    projected_entities = _project_records(entities, ("entity_code", "entity_name", "region", "currency"))
    projected_periods = _project_records(periods, ("period_name", "start_date", "end_date", "status"))
    projected_tasks = sorted(
        _project_records(close_tasks, ("task_id", "period_name", "name", "status", "owner")),
        key=lambda record: str(record.get("task_id", "")),
    )
    projected_exceptions = _project_exception_records(exceptions)
    projected_evidence = _project_evidence_records(evidence)
    projected_metrics = _project_metrics(metrics)
    executive_brief = _executive_brief(
        projected_metrics,
        projected_tasks,
        projected_exceptions,
    )

    return {
        "schema_version": STUDIO_OVERVIEW_SCHEMA_VERSION,
        "synthetic_data_only": True,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        "generated_at": _project_text(manifest.get("generated_at", ""), field="generated_at"),
        "source": _contract_source(manifest),
        "workspace": {
            "name": "Finance Controls Workspace",
            "current_period": _current_period(projected_periods),
            "entity_count": len(projected_entities),
            "evidence_count": len(projected_evidence),
            "close_task_count": len(projected_tasks),
        },
        "executive_brief": executive_brief,
        "control_domains": _control_domains(projected_metrics),
        "entity_health": _entity_health(projected_entities, projected_exceptions),
        "metrics": projected_metrics,
        "risk_distribution": _risk_distribution(projected_exceptions),
        "status_distribution": _status_distribution(projected_exceptions),
        "entities": projected_entities,
        "close_tasks": projected_tasks,
        "exceptions": [_overview_exception(record) for record in projected_exceptions[:8]],
        "notices": [
            "Synthetic local demo data only",
            "Read-only experimental Studio preview",
            "No ERP data is uploaded or sent to an external service",
        ],
    }


def _build_exception_queue_payload(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    manifest = payloads["manifest"]
    records = _project_exception_records(_records(payloads["exceptions"], label="exceptions"))
    statuses = _status_distribution(records)
    return {
        "schema_version": STUDIO_EXCEPTION_QUEUE_SCHEMA_VERSION,
        "synthetic_data_only": True,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        "generated_at": _project_text(manifest.get("generated_at", ""), field="generated_at"),
        "source": _contract_source(manifest),
        "summary": {
            "total": len(records),
            "open": sum(1 for record in records if str(record["status"]).lower() == "open"),
            "high_risk": sum(1 for record in records if record["risk_rating"] in {"critical", "high"}),
            "unassigned": sum(1 for record in records if not record["owner"]),
            "entity_count": len({str(record["entity_code"]) for record in records if record["entity_code"]}),
        },
        "risk_distribution": _risk_distribution(records),
        "status_distribution": statuses,
        "exceptions": records,
        "notices": [
            "Synthetic exception queue only",
            "Read-only: review actions remain in the authenticated current Studio",
        ],
    }


def _build_evidence_binder_payload(
    payloads: dict[str, dict[str, Any]],
    overview: dict[str, Any],
) -> dict[str, Any]:
    manifest = payloads["manifest"]
    records = _project_evidence_records(_records(payloads["evidence"], label="evidence"))
    evidence_coverage = next(
        (float(metric["value"]) for metric in overview["metrics"] if metric["key"] == "evidence_coverage"),
        0.0,
    )
    return {
        "schema_version": STUDIO_EVIDENCE_BINDER_SCHEMA_VERSION,
        "synthetic_data_only": True,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        "generated_at": _project_text(manifest.get("generated_at", ""), field="generated_at"),
        "source": _contract_source(manifest),
        "summary": {
            "total": len(records),
            "available": sum(1 for record in records if str(record["evidence_status"]).lower() == "available"),
            "checksum_count": sum(1 for record in records if len(str(record["checksum_sha256"])) == 64),
            "synthetic_redaction_count": sum(
                1 for record in records if str(record["redaction_status"]).lower() == "synthetic"
            ),
            "coverage_percent": evidence_coverage,
        },
        "status_distribution": _evidence_status_distribution(records),
        "evidence": records,
        "notices": [
            "Synthetic evidence metadata only",
            "Checksums are integrity aids and do not constitute an audit opinion or certification",
            "Source files are not served by the modern preview",
        ],
    }


def _build_inventory_control_payload(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    manifest = payloads["manifest"]
    inventory = payloads["inventory"]
    _require_synthetic_payload(inventory, label="inventory")
    records = _records(inventory, label="inventory")
    (
        on_hand,
        movements,
        exceptions,
        count_sessions,
        reorder_signals,
        valuations,
        valuation_reversals,
        cost_layers,
    ) = _project_inventory_records(records)
    _validate_inventory_valuation_reversals(
        valuations, valuation_reversals, cost_layers
    )
    warehouses: dict[str, dict[str, Any]] = {}
    for record in on_hand:
        warehouse_code = str(record["warehouse_code"])
        warehouse = warehouses.setdefault(
            warehouse_code,
            {
                "warehouse_code": warehouse_code,
                "warehouse_name": record["warehouse_name"],
                "entity_code": record["entity_code"],
                "on_hand_lines": 0,
                "negative_lines": 0,
            },
        )
        warehouse["on_hand_lines"] = int(warehouse["on_hand_lines"]) + 1
        warehouse["negative_lines"] = int(warehouse["negative_lines"]) + int(str(record["quantity"]).startswith("-"))
    warehouse_rows = sorted(warehouses.values(), key=lambda record: str(record["warehouse_code"]))
    return {
        "schema_version": STUDIO_INVENTORY_CONTROL_SCHEMA_VERSION,
        "synthetic_data_only": True,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        "generated_at": _project_text(manifest.get("generated_at", ""), field="generated_at"),
        "source": _contract_source(manifest),
        "summary": {
            "item_count": len({str(record["item_code"]) for record in on_hand}),
            "warehouse_count": len(warehouse_rows),
            "location_count": len({f"{record['warehouse_code']}/{record['location_code']}" for record in on_hand}),
            "movement_count": len(movements),
            "posted_movement_count": sum(record["status"] == "Posted" for record in movements),
            "exception_count": len(exceptions),
            "count_session_count": len(count_sessions),
            "reorder_signal_count": len(reorder_signals),
            "valuation_document_count": len(valuations),
            "valuation_reversal_count": len(valuation_reversals),
            "open_cost_layer_count": sum(record["layer_status"] == "Open" for record in cost_layers),
            "finance_draft_count": sum(record["finance_entry_status"] == "Draft" for record in valuations)
            + sum(record["finance_entry_status"] == "Draft" for record in valuation_reversals),
        },
        "warehouses": warehouse_rows,
        "on_hand": on_hand,
        "movements": movements,
        "exceptions": exceptions,
        "count_sessions": count_sessions,
        "reorder_signals": reorder_signals,
        "valuations": valuations,
        "valuation_reversals": valuation_reversals,
        "cost_layers": cost_layers,
        "notices": [
            "Synthetic inventory-control data only",
            "Read-only: Posted refers to the local ReconForge control ledger only",
            "FIFO valuation, reversal, and Finance Draft rows are read-only synthetic previews; Draft does not mean validated posting",
            "No purchasing, automatic finance validation, source-ERP posting, or ERP writeback is performed",
        ],
    }


def _safe_source_dir(source_path: Path | str) -> Path:
    raw = str(source_path)
    if not raw.strip() or _has_control_character(raw):
        raise StudioDemoBridgeError("Unsafe Studio data source path.")
    path = Path(source_path).expanduser()
    if any(part == ".." for part in path.parts):
        raise StudioDemoBridgeError("Unsafe Studio data source path. Parent traversal is not allowed.")
    if path.is_symlink() or not path.exists() or not path.is_dir():
        raise StudioDemoBridgeError("Studio data source must be an existing local demo directory.")
    return path.resolve(strict=True)


def _safe_output_file(output_path: Path | str) -> Path:
    raw = str(output_path)
    if not raw.strip() or _has_control_character(raw):
        raise StudioDemoBridgeError("Unsafe Studio data output path.")
    path = Path(output_path).expanduser()
    if any(part == ".." for part in path.parts):
        raise StudioDemoBridgeError("Unsafe Studio data output path. Parent traversal is not allowed.")
    if path.suffix.lower() != ".json":
        raise StudioDemoBridgeError("Studio data output must use a .json filename.")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise StudioDemoBridgeError("Studio data output must be a regular JSON file.")
    parent = path.parent.resolve(strict=False)
    if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
        raise StudioDemoBridgeError("Studio data output parent must be a regular directory.")
    return (parent / path.name).resolve(strict=False)


def _source_file(source_dir: Path, relative_path: Path) -> Path:
    candidate = (source_dir / relative_path).resolve(strict=False)
    if not _is_relative_to(candidate, source_dir):
        raise StudioDemoBridgeError("Studio data source file escaped the demo directory.")
    if candidate.is_symlink() or not candidate.exists() or not candidate.is_file():
        raise StudioDemoBridgeError(f"Synthetic demo file is missing: {relative_path.as_posix()}")
    return candidate


def _read_object(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_SOURCE_FILE_BYTES:
            raise StudioDemoBridgeError(
                f"Synthetic demo JSON exceeds the {MAX_SOURCE_FILE_BYTES}-byte limit: {path.name}"
            )
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except StudioDemoBridgeError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise StudioDemoBridgeError(f"Synthetic demo JSON is invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise StudioDemoBridgeError(f"Synthetic demo JSON must be an object: {path.name}")
    return value


def _require_synthetic_payload(payload: dict[str, Any], *, label: str) -> None:
    if payload.get("synthetic_data_only") is not True or payload.get("synthetic_data_marker") != SYNTHETIC_DATA_MARKER:
        raise StudioDemoBridgeError(f"Studio data bridge accepts synthetic ReconForge demo {label} only.")


def _records(payload: dict[str, Any], *, label: str) -> list[dict[str, Any]]:
    value = payload.get("records")
    if not isinstance(value, list) or any(not isinstance(record, dict) for record in value):
        raise StudioDemoBridgeError(f"Synthetic demo {label} records are invalid.")
    if len(value) > MAX_SOURCE_RECORDS:
        raise StudioDemoBridgeError(f"Synthetic demo {label} exceeds the {MAX_SOURCE_RECORDS}-record limit.")
    return value


def _project_records(records: Iterable[dict[str, Any]], allowed_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {field: _project_text(record.get(field, ""), field=field) for field in allowed_fields} for record in records
    ]


def _project_exception_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected = _project_records(
        records,
        (
            "source_type",
            "period_name",
            "entity_code",
            "account_code",
            "control_code",
            "risk_rating",
            "owner",
            "status",
            "description",
        ),
    )
    for record in projected:
        risk_rating = str(record["risk_rating"]).lower()
        if risk_rating not in RISK_RATINGS:
            raise StudioDemoBridgeError("Synthetic demo exception risk ratings are invalid.")
        record["risk_rating"] = risk_rating
        record["exception_id"] = _exception_identifier(record)
    return sorted(
        projected,
        key=lambda record: (
            -_risk_rank(str(record.get("risk_rating", ""))),
            str(record.get("source_type", "")),
            str(record.get("description", "")),
            str(record.get("exception_id", "")),
        ),
    )


def _exception_identifier(record: dict[str, Any]) -> str:
    stable_fields = (
        "source_type",
        "period_name",
        "entity_code",
        "account_code",
        "control_code",
        "risk_rating",
        "description",
    )
    material = "\x1f".join(str(record.get(field, "")) for field in stable_fields)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12].upper()
    return f"SYN-EXC-{digest}"


def _overview_exception(record: dict[str, Any]) -> dict[str, Any]:
    return {
        field: record[field]
        for field in (
            "source_type",
            "period_name",
            "entity_code",
            "account_code",
            "control_code",
            "risk_rating",
            "owner",
            "status",
            "description",
        )
    }


def _project_evidence_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected = _project_records(
        records,
        ("evidence_code", "provenance_type", "redaction_status", "evidence_status", "checksum_sha256"),
    )
    for record in projected:
        checksum = str(record["checksum_sha256"]).lower()
        if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
            raise StudioDemoBridgeError("Synthetic demo evidence checksums must be SHA-256 hex values.")
        record["checksum_sha256"] = checksum
    return sorted(projected, key=lambda record: str(record.get("evidence_code", "")))


def _project_inventory_records(
    records: list[dict[str, Any]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    on_hand: list[dict[str, object]] = []
    movements: list[dict[str, object]] = []
    exceptions: list[dict[str, object]] = []
    count_sessions: list[dict[str, object]] = []
    reorder_signals: list[dict[str, object]] = []
    valuations: list[dict[str, object]] = []
    valuation_reversals: list[dict[str, object]] = []
    cost_layers: list[dict[str, object]] = []
    for source in records:
        record_type = _project_text(source.get("record_type", ""), field="record_type")
        if record_type == "on_hand":
            on_hand_record: dict[str, object] = {
                field: _project_text(source.get(field, ""), field=field)
                for field in (
                    "item_code",
                    "item_name",
                    "uom_code",
                    "warehouse_code",
                    "warehouse_name",
                    "location_code",
                    "entity_code",
                    "lot_serial_code",
                    "tracking_type",
                )
            }
            if not all(
                on_hand_record[field]
                for field in (
                    "item_code",
                    "item_name",
                    "uom_code",
                    "warehouse_code",
                    "warehouse_name",
                    "location_code",
                    "entity_code",
                    "tracking_type",
                )
            ):
                raise StudioDemoBridgeError("Synthetic inventory on-hand identity fields are required.")
            if on_hand_record["tracking_type"] not in {"None", "Lot", "Serial"}:
                raise StudioDemoBridgeError("Synthetic inventory tracking type is invalid.")
            on_hand_record["quantity"] = _inventory_quantity(source.get("quantity"), field="quantity")
            on_hand.append(on_hand_record)
        elif record_type == "movement":
            movement_record: dict[str, object] = {
                field: _project_text(source.get(field, ""), field=field)
                for field in (
                    "movement_number",
                    "movement_type",
                    "status",
                    "movement_date",
                    "entity_code",
                    "from_location",
                    "to_location",
                )
            }
            if not all(
                movement_record[field]
                for field in ("movement_number", "movement_type", "status", "movement_date", "entity_code")
            ):
                raise StudioDemoBridgeError("Synthetic inventory movement identity fields are required.")
            if movement_record["movement_type"] not in {"Receipt", "Delivery", "Transfer", "Adjustment"}:
                raise StudioDemoBridgeError("Synthetic inventory movement type is invalid.")
            if movement_record["status"] not in {"Draft", "Posted", "Voided"}:
                raise StudioDemoBridgeError("Synthetic inventory movement status is invalid.")
            line_count = source.get("line_count")
            if isinstance(line_count, bool) or not isinstance(line_count, int) or not 1 <= line_count <= 1_000:
                raise StudioDemoBridgeError("Synthetic inventory movement line count is invalid.")
            movement_record["line_count"] = line_count
            movement_record["quantity"] = _inventory_quantity(source.get("quantity"), field="quantity", positive=True)
            movements.append(movement_record)
        elif record_type == "exception":
            exception_record: dict[str, object] = {
                field: _project_text(source.get(field, ""), field=field)
                for field in ("control_code", "risk_rating", "item_code", "location", "description")
            }
            if not all(
                exception_record[field] for field in ("control_code", "risk_rating", "item_code", "description")
            ):
                raise StudioDemoBridgeError("Synthetic inventory exception identity fields are required.")
            risk_rating = str(exception_record["risk_rating"]).lower()
            if risk_rating not in RISK_RATINGS:
                raise StudioDemoBridgeError("Synthetic inventory exception risk rating is invalid.")
            exception_record["risk_rating"] = risk_rating
            quantity = source.get("quantity", "")
            exception_record["quantity"] = "" if quantity == "" else _inventory_quantity(quantity, field="quantity")
            exception_record["exception_id"] = _inventory_exception_identifier(exception_record)
            exceptions.append(exception_record)
        elif record_type == "count":
            count_record: dict[str, object] = {
                field: _project_text(source.get(field, ""), field=field)
                for field in (
                    "count_number",
                    "status",
                    "count_date",
                    "entity_code",
                    "warehouse_code",
                    "location_code",
                    "adjustment_movement_number",
                )
            }
            if not all(
                count_record[field]
                for field in (
                    "count_number",
                    "status",
                    "count_date",
                    "entity_code",
                    "warehouse_code",
                    "location_code",
                )
            ):
                raise StudioDemoBridgeError("Synthetic inventory count identity fields are required.")
            if count_record["status"] not in {"Draft", "Counting", "Submitted", "Approved", "Cancelled"}:
                raise StudioDemoBridgeError("Synthetic inventory count status is invalid.")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(count_record["count_date"])):
                raise StudioDemoBridgeError("Synthetic inventory count date is invalid.")
            line_count = source.get("line_count")
            counted_line_count = source.get("counted_line_count")
            variance_line_count = source.get("variance_line_count")
            if (
                isinstance(line_count, bool)
                or not isinstance(line_count, int)
                or not 1 <= line_count <= 100_000
                or isinstance(counted_line_count, bool)
                or not isinstance(counted_line_count, int)
                or not 0 <= counted_line_count <= line_count
                or isinstance(variance_line_count, bool)
                or not isinstance(variance_line_count, int)
                or not 0 <= variance_line_count <= counted_line_count
            ):
                raise StudioDemoBridgeError("Synthetic inventory count line totals are invalid.")
            if count_record["status"] in {"Submitted", "Approved"} and counted_line_count != line_count:
                raise StudioDemoBridgeError("Submitted synthetic inventory counts require completed lines.")
            count_record["line_count"] = line_count
            count_record["counted_line_count"] = counted_line_count
            count_record["variance_line_count"] = variance_line_count
            count_sessions.append(count_record)
        elif record_type == "reorder_signal":
            signal_record: dict[str, object] = {
                field: _project_text(source.get(field, ""), field=field)
                for field in (
                    "risk_rating",
                    "item_code",
                    "item_name",
                    "uom_code",
                    "warehouse_code",
                    "location_code",
                )
            }
            if not all(signal_record.values()):
                raise StudioDemoBridgeError("Synthetic inventory reorder signal identity fields are required.")
            risk_rating = str(signal_record["risk_rating"]).lower()
            if risk_rating not in {"high", "medium"}:
                raise StudioDemoBridgeError("Synthetic inventory reorder signal risk rating is invalid.")
            signal_record["risk_rating"] = risk_rating
            for field in (
                "on_hand_quantity",
                "minimum_quantity",
                "target_quantity",
                "suggested_quantity",
            ):
                signal_record[field] = _inventory_quantity(source.get(field), field=field)
            on_hand_quantity = Decimal(str(signal_record["on_hand_quantity"]))
            minimum = Decimal(str(signal_record["minimum_quantity"]))
            target = Decimal(str(signal_record["target_quantity"]))
            suggested = Decimal(str(signal_record["suggested_quantity"]))
            if (
                minimum < 0
                or target <= minimum
                or on_hand_quantity > minimum
                or suggested <= 0
                or suggested != target - on_hand_quantity
            ):
                raise StudioDemoBridgeError("Synthetic inventory reorder signal quantities are inconsistent.")
            lead_time_days = source.get("lead_time_days")
            if isinstance(lead_time_days, bool) or not isinstance(lead_time_days, int) or not 0 <= lead_time_days <= 3650:
                raise StudioDemoBridgeError("Synthetic inventory reorder lead time is invalid.")
            signal_record["lead_time_days"] = lead_time_days
            signal_record["signal_id"] = _inventory_signal_identifier(signal_record)
            reorder_signals.append(signal_record)
        elif record_type == "valuation":
            valuation_record: dict[str, object] = {
                field: _project_text(source.get(field, ""), field=field)
                for field in (
                    "valuation_number",
                    "movement_number",
                    "movement_type",
                    "status",
                    "valuation_date",
                    "entity_code",
                    "costing_method",
                    "currency_code",
                    "finance_entry_number",
                    "finance_entry_status",
                )
            }
            if not all(
                valuation_record[field]
                for field in (
                    "valuation_number",
                    "movement_number",
                    "movement_type",
                    "status",
                    "valuation_date",
                    "entity_code",
                    "costing_method",
                    "currency_code",
                )
            ):
                raise StudioDemoBridgeError("Synthetic inventory valuation identity fields are required.")
            if valuation_record["movement_type"] not in {"Receipt", "Delivery", "Adjustment"}:
                raise StudioDemoBridgeError("Synthetic inventory valuation movement type is invalid.")
            if valuation_record["status"] not in {"Draft", "Approved", "Cancelled"}:
                raise StudioDemoBridgeError("Synthetic inventory valuation status is invalid.")
            if valuation_record["costing_method"] != "FIFO":
                raise StudioDemoBridgeError("Synthetic inventory valuation method must be FIFO.")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(valuation_record["valuation_date"])):
                raise StudioDemoBridgeError("Synthetic inventory valuation date is invalid.")
            if valuation_record["finance_entry_status"] not in {"", "Draft", "Validated", "Voided"}:
                raise StudioDemoBridgeError("Synthetic Finance Draft status is invalid.")
            if valuation_record["status"] == "Approved" and (
                not valuation_record["finance_entry_number"]
                or not valuation_record["finance_entry_status"]
            ):
                raise StudioDemoBridgeError("Approved synthetic valuations require a Finance Draft reference.")
            valuation_record["total_value"] = _inventory_amount(
                source.get("total_value"), field="total_value", positive=True
            )
            valuations.append(valuation_record)
        elif record_type == "valuation_reversal":
            reversal_record: dict[str, object] = {
                field: _project_text(source.get(field, ""), field=field)
                for field in (
                    "reversal_number",
                    "original_valuation_number",
                    "reversal_movement_number",
                    "original_movement_type",
                    "reversal_movement_type",
                    "status",
                    "reversal_date",
                    "entity_code",
                    "currency_code",
                    "layer_effect",
                    "finance_entry_number",
                    "finance_entry_status",
                )
            }
            if not all(
                reversal_record[field]
                for field in (
                    "reversal_number",
                    "original_valuation_number",
                    "reversal_movement_number",
                    "original_movement_type",
                    "reversal_movement_type",
                    "status",
                    "reversal_date",
                    "entity_code",
                    "currency_code",
                    "layer_effect",
                )
            ):
                raise StudioDemoBridgeError(
                    "Synthetic valuation reversal identity fields are required."
                )
            expected_type = {
                "Receipt": "Delivery",
                "Delivery": "Receipt",
                "Adjustment": "Adjustment",
            }.get(str(reversal_record["original_movement_type"]))
            if expected_type is None or reversal_record["reversal_movement_type"] != expected_type:
                raise StudioDemoBridgeError(
                    "Synthetic valuation reversal movement types are inconsistent."
                )
            if reversal_record["status"] not in {"Draft", "Approved", "Cancelled"}:
                raise StudioDemoBridgeError("Synthetic valuation reversal status is invalid.")
            if reversal_record["layer_effect"] not in {"Restore", "Remove"}:
                raise StudioDemoBridgeError("Synthetic valuation reversal layer effect is invalid.")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(reversal_record["reversal_date"])):
                raise StudioDemoBridgeError("Synthetic valuation reversal date is invalid.")
            if reversal_record["finance_entry_status"] not in {"", "Draft", "Validated", "Voided"}:
                raise StudioDemoBridgeError("Synthetic reversal Finance Draft status is invalid.")
            if reversal_record["status"] == "Approved" and (
                not reversal_record["finance_entry_number"]
                or not reversal_record["finance_entry_status"]
            ):
                raise StudioDemoBridgeError(
                    "Approved synthetic valuation reversals require a Finance Draft reference."
                )
            layer_effect_count = source.get("layer_effect_count")
            if (
                isinstance(layer_effect_count, bool)
                or not isinstance(layer_effect_count, int)
                or not 1 <= layer_effect_count <= 100_000
            ):
                raise StudioDemoBridgeError(
                    "Synthetic valuation reversal layer-effect count is invalid."
                )
            reversal_record["layer_effect_count"] = layer_effect_count
            reversal_record["total_value"] = _inventory_amount(
                source.get("total_value"), field="total_value", positive=True
            )
            valuation_reversals.append(reversal_record)
        elif record_type == "cost_layer":
            layer_record: dict[str, object] = {
                field: _project_text(source.get(field, ""), field=field)
                for field in (
                    "layer_id",
                    "valuation_number",
                    "item_code",
                    "item_name",
                    "uom_code",
                    "lot_serial_code",
                    "entity_code",
                    "currency_code",
                )
            }
            if not all(
                layer_record[field]
                for field in (
                    "layer_id",
                    "valuation_number",
                    "item_code",
                    "item_name",
                    "uom_code",
                    "entity_code",
                    "currency_code",
                )
            ):
                raise StudioDemoBridgeError("Synthetic FIFO cost-layer identity fields are required.")
            layer_record["original_quantity"] = _inventory_quantity(
                source.get("original_quantity"), field="original_quantity", positive=True
            )
            layer_record["remaining_quantity"] = _inventory_quantity(
                source.get("remaining_quantity"), field="remaining_quantity"
            )
            layer_record["original_value"] = _inventory_amount(
                source.get("original_value"), field="original_value", positive=True
            )
            layer_record["remaining_value"] = _inventory_amount(
                source.get("remaining_value"), field="remaining_value"
            )
            original_quantity = Decimal(str(layer_record["original_quantity"]))
            remaining_quantity = Decimal(str(layer_record["remaining_quantity"]))
            original_value = Decimal(str(layer_record["original_value"]))
            remaining_value = Decimal(str(layer_record["remaining_value"]))
            if (
                remaining_quantity < 0
                or remaining_quantity > original_quantity
                or remaining_value < 0
                or remaining_value > original_value
                or (remaining_quantity == 0) != (remaining_value == 0)
            ):
                raise StudioDemoBridgeError("Synthetic FIFO cost-layer balances are inconsistent.")
            layer_record["layer_status"] = "Open" if remaining_quantity > 0 else "Closed"
            cost_layers.append(layer_record)
        else:
            raise StudioDemoBridgeError("Synthetic inventory record type is invalid.")
    on_hand.sort(
        key=lambda record: (
            str(record["warehouse_code"]),
            str(record["location_code"]),
            str(record["item_code"]),
            str(record["lot_serial_code"]),
        )
    )
    movements.sort(key=lambda record: (str(record["movement_date"]), str(record["movement_number"])), reverse=True)
    exceptions.sort(
        key=lambda record: (
            -_risk_rank(str(record["risk_rating"])),
            str(record["control_code"]),
            str(record["exception_id"]),
        )
    )
    count_sessions.sort(
        key=lambda record: (str(record["count_date"]), str(record["count_number"])),
        reverse=True,
    )
    reorder_signals.sort(
        key=lambda record: (
            -_risk_rank(str(record["risk_rating"])),
            str(record["item_code"]),
            str(record["signal_id"]),
        )
    )
    valuations.sort(
        key=lambda record: (str(record["valuation_date"]), str(record["valuation_number"])),
        reverse=True,
    )
    valuation_reversals.sort(
        key=lambda record: (str(record["reversal_date"]), str(record["reversal_number"])),
        reverse=True,
    )
    cost_layers.sort(
        key=lambda record: (str(record["entity_code"]), str(record["item_code"]), str(record["layer_id"]))
    )
    return (
        on_hand,
        movements,
        exceptions,
        count_sessions,
        reorder_signals,
        valuations,
        valuation_reversals,
        cost_layers,
    )


def _inventory_quantity(value: Any, *, field: str, positive: bool = False) -> str:
    text = _project_text(value, field=field, max_length=40)
    if not re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d{1,6})?", text):
        raise StudioDemoBridgeError("Synthetic inventory quantities must be exact decimal strings.")
    if positive and Decimal(text) <= 0:
        raise StudioDemoBridgeError("Synthetic inventory movement quantities must be positive.")
    return text


def _inventory_amount(value: Any, *, field: str, positive: bool = False) -> str:
    text = _inventory_quantity(value, field=field, positive=positive)
    if text.startswith("-"):
        raise StudioDemoBridgeError("Synthetic inventory valuation amounts cannot be negative.")
    return text


def _validate_inventory_valuation_reversals(
    valuations: list[dict[str, object]],
    reversals: list[dict[str, object]],
    cost_layers: list[dict[str, object]],
) -> None:
    valuations_by_number: dict[str, dict[str, object]] = {}
    for valuation in valuations:
        number = str(valuation["valuation_number"])
        if number in valuations_by_number:
            raise StudioDemoBridgeError("Synthetic inventory valuation numbers must be unique.")
        valuations_by_number[number] = valuation
    reversal_numbers: set[str] = set()
    for reversal in reversals:
        number = str(reversal["reversal_number"])
        if number in reversal_numbers:
            raise StudioDemoBridgeError("Synthetic valuation reversal numbers must be unique.")
        reversal_numbers.add(number)
        original = valuations_by_number.get(str(reversal["original_valuation_number"]))
        if original is None or original["status"] != "Approved":
            raise StudioDemoBridgeError(
                "Synthetic valuation reversals require a linked Approved valuation."
            )
        if any(
            str(reversal[field]) != str(original[original_field])
            for field, original_field in (
                ("original_movement_type", "movement_type"),
                ("entity_code", "entity_code"),
                ("currency_code", "currency_code"),
                ("total_value", "total_value"),
            )
        ):
            raise StudioDemoBridgeError(
                "Synthetic valuation reversal must match its original valuation scope and value."
            )
        if str(reversal["reversal_date"]) < str(original["valuation_date"]):
            raise StudioDemoBridgeError(
                "Synthetic valuation reversal cannot predate its original valuation."
            )
        expected_effect = {
            "Receipt": "Remove",
            "Delivery": "Restore",
        }.get(str(original["movement_type"]))
        if expected_effect is not None and reversal["layer_effect"] != expected_effect:
            raise StudioDemoBridgeError(
                "Synthetic valuation reversal layer effect is inconsistent with its original flow."
            )
        if original["movement_type"] == "Receipt":
            original_layers = [
                layer
                for layer in cost_layers
                if layer["valuation_number"] == original["valuation_number"]
            ]
            if not original_layers or any(
                Decimal(str(layer["remaining_quantity"])) != 0
                or Decimal(str(layer["remaining_value"])) != 0
                for layer in original_layers
            ):
                raise StudioDemoBridgeError(
                    "Synthetic reversed receipt layers must be closed after a Remove effect."
                )


def _inventory_exception_identifier(record: dict[str, object]) -> str:
    material = "\x1f".join(
        str(record.get(field, ""))
        for field in ("control_code", "risk_rating", "item_code", "location", "quantity", "description")
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12].upper()
    return f"SYN-INV-EXC-{digest}"


def _inventory_signal_identifier(record: dict[str, object]) -> str:
    material = "\x1f".join(
        str(record.get(field, ""))
        for field in (
            "risk_rating",
            "item_code",
            "warehouse_code",
            "location_code",
            "on_hand_quantity",
            "minimum_quantity",
            "target_quantity",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12].upper()
    return f"SYN-INV-REORDER-{digest}"


def _project_metrics(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: dict[str, float] = {}
    lineage: dict[str, str] = {}
    for record in records:
        key = _project_text(record.get("metric_key", ""), field="metric_key")
        if key not in METRIC_DEFINITIONS:
            continue
        raw_value = record.get("value", 0)
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise StudioDemoBridgeError("Synthetic demo metric values must be numeric.")
        numeric_value = float(raw_value)
        if not math.isfinite(numeric_value):
            raise StudioDemoBridgeError("Synthetic demo metric values must be finite.")
        values[key] = round(numeric_value, 2)
        lineage[key] = _project_text(record.get("lineage", ""), field="lineage", max_length=500)

    projected = []
    for key, (label, value_format, tone) in METRIC_DEFINITIONS.items():
        projected.append(
            {
                "key": key,
                "label": label,
                "value": values.get(key, 0.0),
                "format": value_format,
                "tone": tone,
                "lineage": lineage.get(key, "Not available in this synthetic snapshot."),
            },
        )
    return projected


def _metric_record(metrics: list[dict[str, Any]], key: str) -> dict[str, Any]:
    for metric in metrics:
        if metric["key"] == key:
            return metric
    raise StudioDemoBridgeError(f"Synthetic showcase metric is unavailable: {key}.")


def _score_status(score: float) -> str:
    if score >= 85:
        return "strong"
    if score >= 60:
        return "watch"
    return "attention"


def _executive_brief(
    metrics: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
) -> dict[str, object]:
    readiness = float(_metric_record(metrics, "period_readiness")["value"])
    high_risk = sum(
        record["risk_rating"] in {"critical", "high"} for record in exceptions
    )
    blocked = sum(str(task["status"]).lower() == "blocked" for task in tasks)
    completed = sum(str(task["status"]).lower() == "complete" for task in tasks)
    open_exceptions = sum(
        str(record["status"]).lower() not in {"closed", "resolved"}
        for record in exceptions
    )
    status = _score_status(readiness)
    if high_risk or blocked:
        status = "attention"
    return {
        "readiness_score": round(readiness, 2),
        "readiness_status": status,
        "high_risk_count": high_risk,
        "open_exception_count": open_exceptions,
        "blocked_task_count": blocked,
        "completed_task_count": completed,
    }


def _control_domains(metrics: list[dict[str, Any]]) -> list[dict[str, object]]:
    definitions = (
        ("close", "close_completion"),
        ("evidence", "evidence_coverage"),
        ("matching", "match_rate"),
        ("controls", "control_effectiveness"),
    )
    records: list[dict[str, object]] = []
    for domain, metric_key in definitions:
        metric = _metric_record(metrics, metric_key)
        score = float(metric["value"])
        records.append(
            {
                "domain": domain,
                "score": round(score, 2),
                "status": _score_status(score),
                "lineage": metric["lineage"],
            }
        )
    return records


def _entity_health(
    entities: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for entity in entities:
        entity_code = str(entity["entity_code"])
        scoped = [
            record for record in exceptions if record["entity_code"] == entity_code
        ]
        high_risk = sum(
            record["risk_rating"] in {"critical", "high"} for record in scoped
        )
        open_exceptions = sum(
            str(record["status"]).lower() not in {"closed", "resolved"}
            for record in scoped
        )
        status = "strong"
        if high_risk >= 3:
            status = "attention"
        elif high_risk or open_exceptions:
            status = "watch"
        records.append(
            {
                "entity_code": entity_code,
                "entity_name": entity["entity_name"],
                "region": entity["region"],
                "currency": entity["currency"],
                "open_exception_count": open_exceptions,
                "high_risk_count": high_risk,
                "status": status,
            }
        )
    return sorted(records, key=lambda record: str(record["entity_code"]))


def _current_period(periods: list[dict[str, Any]]) -> str:
    if not periods:
        return ""
    return max(periods, key=lambda period: str(period.get("end_date", ""))).get("period_name", "")


def _risk_rank(value: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(value.lower(), 0)


def _risk_distribution(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    counts = dict.fromkeys(RISK_RATINGS, 0)
    for record in records:
        risk = str(record.get("risk_rating", "")).lower()
        if risk in counts:
            counts[risk] += 1
    return [{"risk": risk, "count": count} for risk, count in counts.items()]


def _status_distribution(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    for record in records:
        status = _project_text(record.get("status", "Open"), field="status") or "Open"
        counts[status] = counts.get(status, 0) + 1
    return [{"status": status, "count": counts[status]} for status in sorted(counts)]


def _evidence_status_distribution(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    for record in records:
        status = _project_text(record.get("evidence_status", "Unknown"), field="evidence_status") or "Unknown"
        counts[status] = counts.get(status, 0) + 1
    return [{"status": status, "count": counts[status]} for status in sorted(counts)]


def _contract_source(manifest: dict[str, Any]) -> dict[str, object]:
    return {
        "kind": "reconforge-enterprise-demo",
        "local_first": bool(manifest.get("local_first", False)),
        "external_calls": bool(manifest.get("external_calls", True)),
    }


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, default=json_default, allow_nan=False)
            handle.write("\n")
        os.replace(temp_path, path)
    except (OSError, TypeError, ValueError):
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _project_text(value: Any, *, field: str, max_length: int = MAX_CONTRACT_TEXT_LENGTH) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise StudioDemoBridgeError(f"Synthetic demo field must be a scalar value: {field}")
    if isinstance(value, float) and not math.isfinite(value):
        raise StudioDemoBridgeError(f"Synthetic demo field must be finite: {field}")
    text = str(value)
    if _has_control_character(text):
        raise StudioDemoBridgeError(f"Synthetic demo field contains control characters: {field}")
    return text[:max_length]


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value is not allowed: {value}")


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
