"""Pure, network-free verification of pinned public financial datasets."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reconforge.reconciliation.deterministic_engine import DeterministicMatchingEngine
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY

PUBLIC_DATA_HOSTS = frozenset(
    {
        "admin.opendatani.gov.uk",
        "api.fiscaldata.treasury.gov",
        "datacatalogapi.worldbank.org",
    }
)
PUBLIC_METADATA_HOSTS = frozenset(
    {
        "ckan.publishing.service.gov.uk",
        "financesone.worldbank.org",
        "fiscaldata.treasury.gov",
    }
)
MANIFEST_SCHEMA = "reconforge-public-financial-evidence-manifest-v1"
REPORT_SCHEMA = "reconforge-public-financial-evidence-report-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
_MONEY = re.compile(r"^-?[0-9]+(?:\.[0-9]{1,2})?$")
_WORLD_BANK_NUMERIC_FIELDS = frozenset(
    {
        "development_policy",
        "investment_lending",
        "private_sector_window",
        "program_for_results",
        "total",
    }
)
_TREASURY_FIELDS = (
    "record_date",
    "debt_held_public_amt",
    "intragov_hold_amt",
    "tot_pub_debt_out_amt",
    "src_line_nbr",
    "record_fiscal_year",
    "record_fiscal_quarter",
    "record_calendar_year",
    "record_calendar_quarter",
    "record_calendar_month",
    "record_calendar_day",
)
_WORLD_BANK_FIELDS = (
    "category",
    "country",
    "development_policy",
    "investment_lending",
    "organization",
    "private_sector_window",
    "program_for_results",
    "region",
    "time_period",
    "total",
)
_UK_FIELDS = (
    "Department",
    "Organisation",
    "Check Date",
    "Expense type",
    "Supplier",
    "Invoice number",
    "Invoice Amount",
    "Postcode",
)
_UK_CANONICAL_FIELDS = (
    "month",
    "department",
    "organisation",
    "check_date",
    "expense_type",
    "supplier",
    "invoice_number",
    "amount",
    "postcode",
    "currency",
)


class PublicFinancialEvidenceError(ValueError):
    """Raised when public evidence violates its closed integrity contract."""


def _validate_safe_id(value: str) -> str:
    if _SAFE_ID.fullmatch(value) is None:
        raise ValueError("id must be a closed lowercase identifier")
    return value


def _validate_digest(value: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise ValueError("digest must be lowercase SHA-256")
    return value


class ArtifactSpec(BaseModel):
    """One immutable public-data response expected by the evidence manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    publisher: str = Field(min_length=2, max_length=120)
    dataset: str = Field(min_length=2, max_length=200)
    license: str = Field(min_length=2, max_length=160)
    metadata_url: str
    url: str
    format: Literal["json", "csv"]
    encoding: Literal["utf-8", "utf-8-sig", "cp1252", "auto-strict"]
    expected_sha256: str
    max_bytes: int = Field(ge=1, le=5_000_000)
    allowed_content_types: tuple[str, ...] = Field(min_length=1, max_length=6)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if _SAFE_ID.fullmatch(value) is None:
            raise ValueError("artifact id must be a closed lowercase identifier")
        return value

    @field_validator("expected_sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("artifact SHA-256 must be lowercase hexadecimal")
        return value

    @field_validator("url")
    @classmethod
    def _validate_data_url(cls, value: str) -> str:
        _validate_https_url(value, hosts=PUBLIC_DATA_HOSTS, label="data URL")
        return value

    @field_validator("metadata_url")
    @classmethod
    def _validate_metadata_url(cls, value: str) -> str:
        _validate_https_url(value, hosts=PUBLIC_METADATA_HOSTS, label="metadata URL")
        return value

    @field_validator("allowed_content_types")
    @classmethod
    def _validate_content_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip().lower() for value in values)
        if any(not value or "/" not in value or ";" in value for value in normalized):
            raise ValueError("content types must be exact media types without parameters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("content types must be unique")
        return normalized


class TreasuryDebtExperiment(BaseModel):
    """Cross-format parity and debt equation for Treasury debt records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Literal["treasury-debt-cross-format"]
    artifact_ids: tuple[str, str]
    expected_record_count: int = Field(ge=1, le=10_000)
    expected_canonical_sha256: str
    expected_equation_violations: int = Field(ge=0)

    _id = field_validator("id")(_validate_safe_id)
    _digest = field_validator("expected_canonical_sha256")(_validate_digest)


class WorldBankExperiment(BaseModel):
    """Paged cross-format parity and component-total equation for World Bank data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Literal["world-bank-cross-format"]
    json_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    csv_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    selected_time_period: str = Field(min_length=2, max_length=20)
    accounting_date: date
    expected_source_record_count: int = Field(ge=1, le=100_000)
    expected_selected_record_count: int = Field(ge=1, le=100_000)
    expected_canonical_sha256: str
    expected_component_equation_violations: int = Field(ge=0)

    _id = field_validator("id")(_validate_safe_id)
    _digest = field_validator("expected_canonical_sha256")(_validate_digest)


class UkSpendingExperiment(BaseModel):
    """Strict mixed-encoding ingestion and deterministic replay of UK spending."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Literal["uk-spending-ingress-replay"]
    artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=24)
    period_by_artifact: dict[str, str]
    expected_encoding_by_artifact: dict[str, Literal["utf-8-sig", "cp1252"]]
    expected_rows_by_artifact: dict[str, int]
    expected_totals_by_artifact: dict[str, str]
    expected_digests_by_artifact: dict[str, str]
    expected_record_count: int = Field(ge=1, le=100_000)
    expected_canonical_sha256: str
    expected_negative_amount_count: int = Field(ge=0)
    expected_reference_collision_groups: int = Field(ge=0)
    expected_threshold_violations: int = Field(ge=0)

    _id = field_validator("id")(_validate_safe_id)
    _digest = field_validator("expected_canonical_sha256")(_validate_digest)

    @field_validator("expected_digests_by_artifact")
    @classmethod
    def _validate_period_digests(cls, values: dict[str, str]) -> dict[str, str]:
        if any(_SHA256.fullmatch(value) is None for value in values.values()):
            raise ValueError("per-artifact canonical digests must be lowercase SHA-256")
        return values


ExperimentSpec = Annotated[
    TreasuryDebtExperiment | WorldBankExperiment | UkSpendingExperiment,
    Field(discriminator="kind"),
]


class PublicFinancialEvidenceManifest(BaseModel):
    """Closed manifest for all public-data evidence inputs and assertions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["reconforge-public-financial-evidence-manifest-v1"]
    manifest_id: str
    captured_at: datetime
    artifacts: tuple[ArtifactSpec, ...] = Field(min_length=1, max_length=40)
    experiments: tuple[ExperimentSpec, ...] = Field(min_length=3, max_length=3)

    _id = field_validator("manifest_id")(_validate_safe_id)

    @field_validator("captured_at")
    @classmethod
    def _validate_captured_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include an explicit timezone")
        return value

    @model_validator(mode="after")
    def _validate_cross_references(self) -> PublicFinancialEvidenceManifest:
        artifact_ids = [artifact.id for artifact in self.artifacts]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("artifact ids must be unique")
        experiment_ids = [experiment.id for experiment in self.experiments]
        if len(set(experiment_ids)) != len(experiment_ids):
            raise ValueError("experiment ids must be unique")
        if {experiment.kind for experiment in self.experiments} != {
            "treasury-debt-cross-format",
            "world-bank-cross-format",
            "uk-spending-ingress-replay",
        }:
            raise ValueError("manifest must contain exactly the three governed public experiments")
        referenced: list[str] = []
        for experiment in self.experiments:
            if isinstance(experiment, TreasuryDebtExperiment | UkSpendingExperiment):
                referenced.extend(experiment.artifact_ids)
            else:
                referenced.extend(experiment.json_artifact_ids)
                referenced.extend(experiment.csv_artifact_ids)
        if len(referenced) != len(set(referenced)):
            raise ValueError("an artifact may belong to only one experiment")
        if set(referenced) != set(artifact_ids):
            raise ValueError("every artifact must be referenced exactly once")
        return self


def _validate_https_url(value: str, *, hosts: frozenset[str], label: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not parsed.path.startswith("/")
        or parsed.fragment
    ):
        raise ValueError(f"{label} must use an exact allowlisted HTTPS origin")


def load_public_financial_manifest(path: Path | str) -> PublicFinancialEvidenceManifest:
    """Safely parse and close one public-evidence manifest."""

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return PublicFinancialEvidenceManifest.model_validate(raw)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise PublicFinancialEvidenceError("Public financial evidence manifest is invalid.") from exc


def canonical_sha256(value: object) -> str:
    """Hash one JSON-safe value using the repository's deterministic JSON basis."""

    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _decimal_text(value: object) -> str:
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PublicFinancialEvidenceError("A public financial amount is malformed.") from exc
    if not parsed.is_finite():
        raise PublicFinancialEvidenceError("A public financial amount must be finite.")
    if parsed == 0:
        return "0"
    return format(parsed.normalize(), "f")


def _fixed_money_text(value: object, *, currency: str) -> str:
    text = str(value).strip()
    if currency == "GBP":
        negative = text.startswith("-")
        if negative:
            text = text[1:]
        if text.startswith("£"):
            text = text[1:]
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        elif negative:
            text = "-" + text
        text = text.replace(",", "")
        if _MONEY.fullmatch(text) is None:
            raise PublicFinancialEvidenceError("A GBP source amount is malformed.")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise PublicFinancialEvidenceError("A public financial amount is malformed.") from exc
    if not parsed.is_finite():
        raise PublicFinancialEvidenceError("A public financial amount violates two-decimal precision.")
    exponent = parsed.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise PublicFinancialEvidenceError("A public financial amount violates two-decimal precision.")
    return format(parsed.quantize(Decimal("0.01")), "f")


def _strict_csv_rows(content: bytes, spec: ArtifactSpec, expected_fields: Sequence[str]) -> tuple[list[dict[str, str]], str]:
    encoding = spec.encoding
    if encoding == "auto-strict":
        try:
            text = content.decode("utf-8-sig", errors="strict")
            encoding = "utf-8-sig"
        except UnicodeDecodeError:
            text = content.decode("cp1252", errors="strict")
            encoding = "cp1252"
    else:
        try:
            text = content.decode(encoding, errors="strict")
        except UnicodeDecodeError as exc:
            raise PublicFinancialEvidenceError(f"Artifact {spec.id} violates its declared encoding.") from exc
    if "\x00" in text:
        raise PublicFinancialEvidenceError(f"Artifact {spec.id} contains a prohibited NUL byte.")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != tuple(expected_fields):
        raise PublicFinancialEvidenceError(f"Artifact {spec.id} has an unsupported CSV schema.")
    rows = list(reader)
    if not rows or any(
        None in row
        or set(row) != set(expected_fields)
        or any(value is None for value in row.values())
        for row in rows
    ):
        raise PublicFinancialEvidenceError(f"Artifact {spec.id} has malformed CSV rows.")
    return [{key: str(value) for key, value in row.items()} for row in rows], encoding


def _closed_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PublicFinancialEvidenceError("Public financial JSON contains a duplicate object key.")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise PublicFinancialEvidenceError(f"Public financial JSON contains prohibited constant {value}.")


def _strict_json(content: bytes, spec: ArtifactSpec) -> dict[str, Any]:
    try:
        decoded = content.decode(spec.encoding, errors="strict")
        value = json.loads(
            decoded,
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_closed_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicFinancialEvidenceError(f"Artifact {spec.id} is not valid declared JSON.") from exc
    if not isinstance(value, dict):
        raise PublicFinancialEvidenceError(f"Artifact {spec.id} must contain a JSON object.")
    return value


def _artifact_map(manifest: PublicFinancialEvidenceManifest) -> dict[str, ArtifactSpec]:
    return {artifact.id: artifact for artifact in manifest.artifacts}


def _verify_artifacts(
    manifest: PublicFinancialEvidenceManifest,
    contents: Mapping[str, bytes],
) -> list[dict[str, object]]:
    expected = {artifact.id for artifact in manifest.artifacts}
    if set(contents) != expected:
        raise PublicFinancialEvidenceError("Artifact payload ids do not exactly match the manifest.")
    receipts: list[dict[str, object]] = []
    for artifact in manifest.artifacts:
        content = contents[artifact.id]
        if not isinstance(content, bytes) or not content or len(content) > artifact.max_bytes:
            raise PublicFinancialEvidenceError(f"Artifact {artifact.id} violates its bounded size contract.")
        digest = hashlib.sha256(content).hexdigest()
        if digest != artifact.expected_sha256:
            raise PublicFinancialEvidenceError(f"Artifact {artifact.id} failed SHA-256 verification.")
        receipts.append(
            {
                "id": artifact.id,
                "publisher": artifact.publisher,
                "dataset": artifact.dataset,
                "license": artifact.license,
                "metadata_url": artifact.metadata_url,
                "bytes": len(content),
                "sha256": digest,
            }
        )
    return receipts


def _currency_precision(currency_code: str) -> tuple[int | None, str | None]:
    return (2, None) if currency_code in {"GBP", "USD"} else (None, "UNKNOWN_CURRENCY")


def _match_summary(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, object]:
    engine = DeterministicMatchingEngine(_currency_precision)
    options: dict[str, Any] = {
        "left_records": left,
        "right_records": right,
        "exact_fields": "currency",
        "record_identity_policy": RECORD_IDENTITY_POLICY,
    }
    output = engine.match_records(**options)
    permuted = engine.match_records(
        **{
            **options,
            "left_records": list(reversed(left)),
            "right_records": list(reversed(right)),
        }
    )
    if output != permuted:
        raise PublicFinancialEvidenceError("Matching output changed under row permutation.")
    statuses = Counter(str(result.get("status")) for result in output.results)
    if statuses != {"Matched": len(left)} or len(left) != len(right) or output.exceptions:
        raise PublicFinancialEvidenceError("Public evidence did not produce exact deterministic parity.")
    return {
        "matched_count": statuses["Matched"],
        "unmatched_count": 0,
        "exception_count": 0,
        "permutation_equal": True,
        "decision_sha256": canonical_sha256(
            {
                "results": output.results,
                "exceptions": output.exceptions,
                "financial_input_policy": output.financial_input_policy,
                "record_identity_policy": output.record_identity_policy,
            }
        ),
    }


def _normalize_treasury_record(row: Mapping[str, object]) -> dict[str, str]:
    if set(row) != set(_TREASURY_FIELDS):
        raise PublicFinancialEvidenceError("Treasury record schema expanded or contracted.")
    try:
        date.fromisoformat(str(row["record_date"]))
    except ValueError as exc:
        raise PublicFinancialEvidenceError("Treasury record date is invalid.") from exc
    normalized = {key: str(row[key]).strip() for key in _TREASURY_FIELDS}
    for key in ("debt_held_public_amt", "intragov_hold_amt", "tot_pub_debt_out_amt"):
        normalized[key] = _fixed_money_text(row[key], currency="USD")
    for key in _TREASURY_FIELDS[4:]:
        if not normalized[key].isdigit():
            raise PublicFinancialEvidenceError("Treasury record contains an invalid integer dimension.")
    return normalized


def _treasury_records(content: bytes, spec: ArtifactSpec) -> list[dict[str, str]]:
    if spec.format == "json":
        document = _strict_json(content, spec)
        data = document.get("data")
        if not isinstance(data, list):
            raise PublicFinancialEvidenceError("Treasury JSON is missing its data array.")
        rows = [_normalize_treasury_record(row) for row in data if isinstance(row, dict)]
        meta = document.get("meta")
        if not isinstance(meta, dict) or str(meta.get("total-count")) != str(len(rows)):
            raise PublicFinancialEvidenceError("Treasury JSON count metadata is inconsistent.")
    else:
        csv_rows, _encoding = _strict_csv_rows(content, spec, _TREASURY_FIELDS)
        rows = [_normalize_treasury_record(row) for row in csv_rows]
    return sorted(rows, key=lambda row: row["record_date"])


def _run_treasury(
    experiment: TreasuryDebtExperiment,
    specs: Mapping[str, ArtifactSpec],
    contents: Mapping[str, bytes],
) -> dict[str, object]:
    first, second = (specs[artifact_id] for artifact_id in experiment.artifact_ids)
    if {first.format, second.format} != {"json", "csv"}:
        raise PublicFinancialEvidenceError("Treasury experiment requires one JSON and one CSV artifact.")
    by_format = {spec.format: _treasury_records(contents[spec.id], spec) for spec in (first, second)}
    if by_format["json"] != by_format["csv"]:
        raise PublicFinancialEvidenceError("Treasury JSON and CSV semantics differ.")
    records = by_format["json"]
    digest = canonical_sha256(records)
    equation_violations = sum(
        Decimal(row["debt_held_public_amt"]) + Decimal(row["intragov_hold_amt"])
        != Decimal(row["tot_pub_debt_out_amt"])
        for row in records
    )
    if (
        len(records) != experiment.expected_record_count
        or digest != experiment.expected_canonical_sha256
        or equation_violations != experiment.expected_equation_violations
    ):
        raise PublicFinancialEvidenceError("Treasury experiment no longer matches its governed baseline.")
    left = [
        {
            "id": f"T-J-{row['record_date']}",
            "reference": row["record_date"],
            "amount": row["tot_pub_debt_out_amt"],
            "currency": "USD",
            "date": row["record_date"],
        }
        for row in records
    ]
    right = [{**row, "id": row["id"].replace("T-J-", "T-C-")} for row in left]
    return {
        "id": experiment.id,
        "kind": experiment.kind,
        "status": "passed",
        "record_count": len(records),
        "canonical_sha256": digest,
        "cross_format_equal": True,
        "debt_equation_violations": equation_violations,
        "matching": _match_summary(left, right),
    }


def _normalize_world_bank_record(row: Mapping[str, object]) -> dict[str, str]:
    if set(row) != set(_WORLD_BANK_FIELDS):
        raise PublicFinancialEvidenceError("World Bank record schema expanded or contracted.")
    normalized: dict[str, str] = {}
    for key in _WORLD_BANK_FIELDS:
        value = row[key]
        normalized[key] = _decimal_text(value) if key in _WORLD_BANK_NUMERIC_FIELDS else str(value).strip()
    if any(not normalized[key] for key in set(_WORLD_BANK_FIELDS) - _WORLD_BANK_NUMERIC_FIELDS):
        raise PublicFinancialEvidenceError("World Bank record has a missing identity dimension.")
    return normalized


def _world_bank_json_records(content: bytes, spec: ArtifactSpec) -> tuple[int, list[dict[str, str]]]:
    document = _strict_json(content, spec)
    if set(document) != {"count", "data"} or not isinstance(document["count"], int):
        raise PublicFinancialEvidenceError("World Bank page metadata is unsupported.")
    data = document["data"]
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise PublicFinancialEvidenceError("World Bank JSON page is malformed.")
    return document["count"], [_normalize_world_bank_record(row) for row in data]


def _world_bank_csv_records(content: bytes, spec: ArtifactSpec) -> list[dict[str, str]]:
    rows, _encoding = _strict_csv_rows(content, spec, _WORLD_BANK_FIELDS)
    return [_normalize_world_bank_record(row) for row in rows]


def _world_bank_sort_key(row: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(row[key] for key in _WORLD_BANK_FIELDS)


def _run_world_bank(
    experiment: WorldBankExperiment,
    specs: Mapping[str, ArtifactSpec],
    contents: Mapping[str, bytes],
) -> dict[str, object]:
    json_records: list[dict[str, str]] = []
    source_counts: set[int] = set()
    for artifact_id in experiment.json_artifact_ids:
        spec = specs[artifact_id]
        if spec.format != "json":
            raise PublicFinancialEvidenceError("World Bank JSON page has the wrong format declaration.")
        source_count, rows = _world_bank_json_records(contents[artifact_id], spec)
        source_counts.add(source_count)
        json_records.extend(rows)
    csv_records: list[dict[str, str]] = []
    for artifact_id in experiment.csv_artifact_ids:
        spec = specs[artifact_id]
        if spec.format != "csv":
            raise PublicFinancialEvidenceError("World Bank CSV page has the wrong format declaration.")
        csv_records.extend(_world_bank_csv_records(contents[artifact_id], spec))
    json_records.sort(key=_world_bank_sort_key)
    csv_records.sort(key=_world_bank_sort_key)
    if (
        source_counts != {experiment.expected_source_record_count}
        or len(json_records) != experiment.expected_source_record_count
        or json_records != csv_records
    ):
        raise PublicFinancialEvidenceError("World Bank pagination or cross-format parity failed.")
    selected = [row for row in json_records if row["time_period"] == experiment.selected_time_period]
    digest = canonical_sha256(selected)
    equation_violations = 0
    for row in selected:
        component_total = sum(
            (Decimal(row[field]) for field in _WORLD_BANK_NUMERIC_FIELDS if field != "total"),
            Decimal(0),
        )
        equation_violations += component_total != Decimal(row["total"])
    identity_fields = ("organization", "time_period", "category", "region", "country")
    identities = [tuple(row[field] for field in identity_fields) for row in selected]
    if len(set(identities)) != len(identities):
        raise PublicFinancialEvidenceError("World Bank selected records contain duplicate business identities.")
    if (
        len(selected) != experiment.expected_selected_record_count
        or digest != experiment.expected_canonical_sha256
        or equation_violations != experiment.expected_component_equation_violations
    ):
        raise PublicFinancialEvidenceError("World Bank experiment no longer matches its governed baseline.")
    left: list[dict[str, Any]] = []
    right: list[dict[str, Any]] = []
    for row in selected:
        reference = canonical_sha256({field: row[field] for field in identity_fields})
        left.append(
            {
                "id": "WB-J-" + reference[:24],
                "reference": reference,
                "amount": row["total"],
                "currency": "USD",
                "date": experiment.accounting_date.isoformat(),
            }
        )
        right.append({**left[-1], "id": "WB-C-" + reference[:24]})
    return {
        "id": experiment.id,
        "kind": experiment.kind,
        "status": "passed",
        "source_record_count": len(json_records),
        "selected_record_count": len(selected),
        "selected_time_period": experiment.selected_time_period,
        "canonical_sha256": digest,
        "cross_format_equal": True,
        "component_equation_violations": equation_violations,
        "matching": _match_summary(left, right),
    }


def _uk_canonical_record(row: Mapping[str, str], *, period: str) -> dict[str, str]:
    if any(not row[field].strip() for field in _UK_FIELDS):
        raise PublicFinancialEvidenceError("UK spending row has a missing required field.")
    try:
        parsed_date = datetime.strptime(row["Check Date"].strip(), "%d/%m/%Y").date()
    except ValueError as exc:
        raise PublicFinancialEvidenceError("UK spending row has an invalid date.") from exc
    if parsed_date.strftime("%Y-%m") != period:
        raise PublicFinancialEvidenceError("UK spending row falls outside its declared period.")
    return {
        "month": period,
        "department": row["Department"].strip(),
        "organisation": row["Organisation"].strip(),
        "check_date": parsed_date.isoformat(),
        "expense_type": row["Expense type"].strip(),
        "supplier": row["Supplier"].strip(),
        "invoice_number": row["Invoice number"].strip(),
        "amount": _fixed_money_text(row["Invoice Amount"], currency="GBP"),
        "postcode": row["Postcode"].strip(),
        "currency": "GBP",
    }


def _uk_sort_key(row: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(row[key] for key in _UK_CANONICAL_FIELDS)


def _run_uk(
    experiment: UkSpendingExperiment,
    specs: Mapping[str, ArtifactSpec],
    contents: Mapping[str, bytes],
) -> dict[str, object]:
    expected_ids = set(experiment.artifact_ids)
    mappings = (
        set(experiment.period_by_artifact),
        set(experiment.expected_encoding_by_artifact),
        set(experiment.expected_rows_by_artifact),
        set(experiment.expected_totals_by_artifact),
        set(experiment.expected_digests_by_artifact),
    )
    if any(keys != expected_ids for keys in mappings):
        raise PublicFinancialEvidenceError("UK experiment mappings must cover every artifact exactly.")
    combined: list[dict[str, str]] = []
    encoding_counts: Counter[str] = Counter()
    negative_amount_count = 0
    reference_collision_groups = 0
    threshold_violations = 0
    period_results: list[dict[str, object]] = []
    for artifact_id in experiment.artifact_ids:
        spec = specs[artifact_id]
        if spec.format != "csv" or spec.encoding != "auto-strict":
            raise PublicFinancialEvidenceError("UK artifacts require strict automatic CSV decoding.")
        rows, encoding = _strict_csv_rows(contents[artifact_id], spec, _UK_FIELDS)
        if encoding != experiment.expected_encoding_by_artifact[artifact_id]:
            raise PublicFinancialEvidenceError("UK source encoding changed from its governed baseline.")
        period = experiment.period_by_artifact[artifact_id]
        canonical = [_uk_canonical_record(row, period=period) for row in rows]
        canonical.sort(key=_uk_sort_key)
        digest = canonical_sha256(canonical)
        total = sum((Decimal(row["amount"]) for row in canonical), Decimal(0))
        references = Counter(row["invoice_number"].upper() for row in canonical)
        collisions = sum(1 for count in references.values() if count > 1)
        negatives = sum(Decimal(row["amount"]) < 0 for row in canonical)
        threshold = sum(abs(Decimal(row["amount"])) < Decimal("25000") for row in canonical)
        if (
            len(canonical) != experiment.expected_rows_by_artifact[artifact_id]
            or format(total, "f") != experiment.expected_totals_by_artifact[artifact_id]
            or digest != experiment.expected_digests_by_artifact[artifact_id]
        ):
            raise PublicFinancialEvidenceError("UK period no longer matches its governed baseline.")
        encoding_counts[encoding] += 1
        negative_amount_count += negatives
        reference_collision_groups += collisions
        threshold_violations += threshold
        combined.extend(canonical)
        period_results.append(
            {
                "artifact_id": artifact_id,
                "period": period,
                "encoding": encoding,
                "record_count": len(canonical),
                "total": format(total, "f"),
                "canonical_sha256": digest,
                "negative_amount_count": negatives,
                "reference_collision_groups": collisions,
                "threshold_violations": threshold,
            }
        )
    combined.sort(key=_uk_sort_key)
    digest = canonical_sha256(combined)
    if (
        len(combined) != experiment.expected_record_count
        or digest != experiment.expected_canonical_sha256
        or negative_amount_count != experiment.expected_negative_amount_count
        or reference_collision_groups != experiment.expected_reference_collision_groups
        or threshold_violations != experiment.expected_threshold_violations
    ):
        raise PublicFinancialEvidenceError("UK combined experiment no longer matches its governed baseline.")
    left: list[dict[str, Any]] = []
    right: list[dict[str, Any]] = []
    for index, row in enumerate(combined, start=1):
        reference = canonical_sha256(row)
        left.append(
            {
                "id": f"UK-L-{reference[:18]}-{index:04d}",
                "reference": reference,
                "amount": row["amount"],
                "currency": "GBP",
                "date": row["check_date"],
            }
        )
        right.append({**left[-1], "id": f"UK-R-{reference[:18]}-{index:04d}"})
    return {
        "id": experiment.id,
        "kind": experiment.kind,
        "status": "passed",
        "record_count": len(combined),
        "canonical_sha256": digest,
        "periods": period_results,
        "encoding_counts": dict(sorted(encoding_counts.items())),
        "negative_amount_count": negative_amount_count,
        "reference_collision_groups": reference_collision_groups,
        "threshold_violations": threshold_violations,
        "matching": _match_summary(left, right),
    }


def run_public_financial_evidence(
    manifest: PublicFinancialEvidenceManifest,
    contents: Mapping[str, bytes],
) -> dict[str, object]:
    """Verify pinned public inputs and run all three deterministic experiments."""

    receipts = _verify_artifacts(manifest, contents)
    specs = _artifact_map(manifest)
    experiment_results: list[dict[str, object]] = []
    for experiment in manifest.experiments:
        if isinstance(experiment, TreasuryDebtExperiment):
            result = _run_treasury(experiment, specs, contents)
        elif isinstance(experiment, WorldBankExperiment):
            result = _run_world_bank(experiment, specs, contents)
        else:
            result = _run_uk(experiment, specs, contents)
        experiment_results.append(result)
    evidence_basis = {
        "manifest_id": manifest.manifest_id,
        "artifact_receipts": receipts,
        "experiments": experiment_results,
    }
    return {
        "schema_version": REPORT_SCHEMA,
        "manifest_id": manifest.manifest_id,
        "manifest_captured_at": manifest.captured_at.isoformat(),
        "status": "passed",
        "artifact_receipts": receipts,
        "experiments": experiment_results,
        "checks": {
            "artifact_integrity": True,
            "closed_schema": True,
            "exact_decimal_financial_inputs": True,
            "cross_format_semantic_parity": True,
            "financial_equations": True,
            "deterministic_matching": True,
            "row_permutation_stability": True,
            "raw_identifiers_excluded_from_report": True,
        },
        "reproducibility_sha256": canonical_sha256(evidence_basis),
        "claim_boundary": {
            "real_public_financial_data": True,
            "external_operator_count": 0,
            "qualifies_as_external_pilot_without_operator_attestation": False,
            "qualifies_as_independent_security_review": False,
        },
        "limitations": [
            "Public-data verification is not a customer production deployment or audit opinion.",
            "A maintainer-run report does not satisfy the independent external-operator gate.",
            "Automated security tooling does not replace a qualified independent security reviewer.",
        ],
    }


__all__ = [
    "ArtifactSpec",
    "MANIFEST_SCHEMA",
    "PUBLIC_DATA_HOSTS",
    "PublicFinancialEvidenceError",
    "PublicFinancialEvidenceManifest",
    "canonical_sha256",
    "load_public_financial_manifest",
    "run_public_financial_evidence",
]
