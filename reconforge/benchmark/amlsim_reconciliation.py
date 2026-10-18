"""Offline, provenance-bound AMLSim sample projection and reconciliation oracle.

Currency and date epoch are explicit ReconForge scenario assignments: the
upstream sample contains neither a currency nor an absolute transaction date.
No generator code executes and no network access occurs in this module.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reconforge.io.structured import read_yaml_document
from reconforge.reconciliation.deterministic_engine import DeterministicMatchingEngine
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY

FIELDS = (
    "TXN_ID", "ACCOUNT_ID", "COUNTER_PARTY_ACCOUNT_NUM", "TXN_SOURCE_TYPE_CODE",
    "tx_count", "TXN_AMOUNT_ORIG", "start", "end",
)
STRICT_POLICY = "strict-one-to-one-v1"
PROJECTION_VERSION = "amlsim-single-transfer-projection-v1"
_INTEGER = re.compile(r"(?:0|[1-9][0-9]{0,17})")
_AMOUNT = re.compile(r"(?:0|[1-9][0-9]{0,99})(?:\.[0-9]{1,18})?")


class AMLSimWorkloadError(ValueError):
    """An input or decision violates the closed workload contract."""


class FaultPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    missing_id: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,17})$")
    changed_amount_id: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,17})$")
    duplicate_id: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,17})$")
    delayed_id: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,17})$")
    amount_delta_minor: int = Field(default=1, strict=True, ge=1, le=1_000_000)
    delay_days: int = Field(default=1, strict=True, ge=1, le=365)

    @model_validator(mode="after")
    def distinct_ids(self) -> FaultPlan:
        if len({self.missing_id, self.changed_amount_id, self.duplicate_id, self.delayed_id}) != 4:
            raise ValueError("Fault source IDs must be distinct.")
        return self


class AMLSimProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["reconforge-amlsim-workload-v1"]
    upstream_repository: Literal["https://github.com/IBM/AMLSim"]
    upstream_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    upstream_path: Literal["sample/outputs/tx.csv"]
    upstream_license: Literal["Apache-2.0"]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_records: int = Field(strict=True, ge=4, le=100_000)
    max_bytes: int = Field(strict=True, ge=1, le=25_000_000)
    assigned_currency: str = Field(pattern=r"^[A-Z]{3}$")
    assigned_minor_units: int = Field(strict=True, ge=0, le=4)
    assigned_epoch: date
    faults: FaultPlan


def load_amlsim_profile(path: Path | str) -> AMLSimProfile:
    return AMLSimProfile.model_validate(read_yaml_document(path))


def canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _minor(text: str, scale: int) -> int:
    if _AMOUNT.fullmatch(text) is None:
        raise AMLSimWorkloadError("Malformed source amount.")
    integer, _, fraction = text.partition(".")
    if len(fraction) > scale:
        raise AMLSimWorkloadError("Source amount exceeds assigned precision.")
    return int(integer) * 10 ** scale + int(fraction.ljust(scale, "0") or "0")


def _amount_text(minor: int, scale: int) -> str:
    integer, remainder = divmod(minor, 10 ** scale)
    return f"{integer}.{remainder:0{scale}d}" if scale else str(integer)


def parse_amlsim_sample(content: bytes, profile: AMLSimProfile) -> list[dict[str, str]]:
    """Validate pinned bytes and derive stable identities without row indexes."""

    if not content or len(content) > profile.max_bytes:
        raise AMLSimWorkloadError("Source exceeds its byte boundary.")
    if hashlib.sha256(content).hexdigest() != profile.input_sha256:
        raise AMLSimWorkloadError("Source SHA-256 mismatch.")
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AMLSimWorkloadError("Source is not UTF-8.") from exc
    if "\x00" in text:
        raise AMLSimWorkloadError("Source contains a NUL byte.")
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        fields = tuple(reader.fieldnames or ())
    except csv.Error as exc:
        raise AMLSimWorkloadError("Malformed source CSV header.") from exc
    if fields != FIELDS:
        raise AMLSimWorkloadError("Unsupported AMLSim CSV schema.")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        for raw in reader:
            if len(rows) >= profile.expected_records or None in raw or any(value is None for value in raw.values()):
                raise AMLSimWorkloadError("Source row count or shape mismatch.")
            if any(_INTEGER.fullmatch(raw[key]) is None for key in ("TXN_ID", "ACCOUNT_ID", "COUNTER_PARTY_ACCOUNT_NUM", "start", "end")):
                raise AMLSimWorkloadError("Invalid source identity or step.")
            source_id = raw["TXN_ID"]
            if source_id in seen:
                raise AMLSimWorkloadError("Duplicate source transaction ID.")
            if raw["tx_count"] != "1" or raw["start"] != raw["end"]:
                raise AMLSimWorkloadError("Aggregated transfers require a different projection.")
            if re.fullmatch(r"[A-Z][A-Z_]{0,31}", raw["TXN_SOURCE_TYPE_CODE"]) is None:
                raise AMLSimWorkloadError("Invalid transfer type.")
            amount = _minor(raw["TXN_AMOUNT_ORIG"], profile.assigned_minor_units)
            try:
                assigned_date = profile.assigned_epoch + timedelta(days=int(raw["start"]))
            except (OverflowError, ValueError) as exc:
                raise AMLSimWorkloadError("Source step exceeds the assigned calendar.") from exc
            seen.add(source_id)
            rows.append({
                "source_id": source_id, "reference": f"AMLSIM-{source_id}",
                "account": raw["ACCOUNT_ID"], "counterparty": raw["COUNTER_PARTY_ACCOUNT_NUM"],
                "transfer_type": raw["TXN_SOURCE_TYPE_CODE"], "source_step": raw["start"],
                "amount": _amount_text(amount, profile.assigned_minor_units),
                "currency": profile.assigned_currency, "date": assigned_date.isoformat(),
            })
    except csv.Error as exc:
        raise AMLSimWorkloadError("Malformed source CSV.") from exc
    if len(rows) != profile.expected_records:
        raise AMLSimWorkloadError("Source record count mismatch.")
    fault_ids = {profile.faults.missing_id, profile.faults.changed_amount_id, profile.faults.duplicate_id, profile.faults.delayed_id}
    if not fault_ids <= seen:
        raise AMLSimWorkloadError("Fault plan refers to absent source IDs.")
    return sorted(rows, key=lambda row: int(row["source_id"]))


def project_sides(rows: list[dict[str, str]], profile: AMLSimProfile) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply declared ReconForge faults, leaving upstream rows unchanged."""

    left = [{**row, "id": "L-" + row["source_id"]} for row in rows]
    right: list[dict[str, Any]] = []
    for row in rows:
        identity = row["source_id"]
        if identity == profile.faults.missing_id:
            continue
        target = {**row, "id": "R-" + identity}
        if identity == profile.faults.changed_amount_id:
            target["amount"] = _amount_text(_minor(row["amount"], profile.assigned_minor_units) + profile.faults.amount_delta_minor, profile.assigned_minor_units)
        if identity == profile.faults.delayed_id:
            try:
                target["date"] = (date.fromisoformat(row["date"]) + timedelta(days=profile.faults.delay_days)).isoformat()
            except OverflowError as exc:
                raise AMLSimWorkloadError("Delayed scenario exceeds the calendar.") from exc
        right.append(target)
        if identity == profile.faults.duplicate_id:
            right.append({**target, "id": "R-" + identity + "-duplicate"})
    return left, right


def run_amlsim_reconciliation(content: bytes, profile: AMLSimProfile) -> dict[str, Any]:
    rows = parse_amlsim_sample(content, profile)
    left, right = project_sides(rows, profile)
    engine = DeterministicMatchingEngine(lambda code: (profile.assigned_minor_units, None) if code == profile.assigned_currency else (None, "UNKNOWN_CURRENCY"))
    options: dict[str, Any] = {
        "exact_fields": "reference,currency,account,counterparty,transfer_type",
        "amount_tolerance": "0", "date_window_days": 0,
        "record_identity_policy": RECORD_IDENTITY_POLICY, "constraint_policy": STRICT_POLICY,
    }
    output = engine.match_records(left_records=left, right_records=right, **options)
    permuted = engine.match_records(left_records=list(reversed(left)), right_records=list(reversed(right)), **options)
    if output != permuted:
        raise AMLSimWorkloadError("Decision changed under source permutation.")
    expected_unmatched_left = {"L-" + identity for identity in (profile.faults.missing_id, profile.faults.changed_amount_id, profile.faults.delayed_id)}
    expected_matched_left = {row["id"] for row in left} - expected_unmatched_left
    matched = [row for row in output.results if row["status"] == "Matched"]
    unmatched_left = {row["left_id"] for row in output.results if row["status"] == "Unmatched" and "left_id" in row}
    unmatched_right = {row["right_id"] for row in output.results if row["status"] == "Unmatched" and "right_id" in row}
    fixed_unmatched_right = {"R-" + identity for identity in (profile.faults.changed_amount_id, profile.faults.delayed_id)}
    duplicate_choices = {"R-" + profile.faults.duplicate_id, "R-" + profile.faults.duplicate_id + "-duplicate"}
    matched_right = [str(row["right_id"]) for row in matched]
    if (
        len(matched) != len(expected_matched_left)
        or {row["left_id"] for row in matched} != expected_matched_left
        or len(set(matched_right)) != len(matched_right)
        or unmatched_left != expected_unmatched_left
        or not fixed_unmatched_right <= unmatched_right
        or len(unmatched_right) != 3
        or len(unmatched_right & duplicate_choices) != 1
        or len(output.results) != len(rows) + 3
        or any(row["status"] not in {"Matched", "Unmatched"} for row in output.results)
        or output.exceptions
    ):
        raise AMLSimWorkloadError("Reconciliation decisions failed the independent fault oracle.")
    for decision in matched:
        identity = str(decision["left_id"])[2:]
        allowed = {"R-" + identity}
        if identity == profile.faults.duplicate_id:
            allowed = duplicate_choices
        if decision["right_id"] not in allowed or _minor(str(decision["amount_difference"]), profile.assigned_minor_units) != 0 or decision["date_difference_days"] != 0:
            raise AMLSimWorkloadError("A selected pair violates exact reconciliation.")
    basis = {
        "projection": PROJECTION_VERSION, "profile_digest": canonical_digest(profile.model_dump(mode="json")),
        "source_digest": profile.input_sha256, "canonical_source_digest": canonical_digest(rows),
        "rule_digest": canonical_digest(options), "decisions": output.results,
    }
    return {
        "schema_version": "reconforge-amlsim-evidence-v1", "status": "passed",
        "source": {"repository": profile.upstream_repository, "commit": profile.upstream_commit, "path": profile.upstream_path, "sha256": profile.input_sha256, "license": profile.upstream_license},
        "projection": PROJECTION_VERSION, "scenario": profile.model_dump(mode="json"),
        "input_records": len(rows), "left_records": len(left), "right_records": len(right),
        "matched_pairs": len(matched), "unmatched_left": len(unmatched_left), "unmatched_right": len(unmatched_right),
        "seeded_faults": {"missing": 1, "amount_changed": 1, "duplicate": 1, "delayed": 1},
        "result_statuses": dict(Counter(str(row["status"]) for row in output.results)),
        "oracle_passed": True, "permutation_equal": True,
        "rule_digest": basis["rule_digest"], "canonical_source_digest": basis["canonical_source_digest"],
        "decision_digest": canonical_digest(output.results), "reproducibility_digest": canonical_digest(basis),
        "limitations": ["synthetic upstream sample", "currency and date epoch assigned by this scenario", "two sides derived from one source", "faults seeded by ReconForge", "in-process matcher only; no PostgreSQL worker or posting", "no customer, AML efficacy, audit acceptance or scale claim"],
    }
